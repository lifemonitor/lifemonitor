# Copyright (c) 2020-2022 CRS4
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import logging
from typing import List, Optional, Set, Union

from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import aliased
from sqlalchemy.orm.collections import (MappedCollection,
                                        attribute_mapped_collection,
                                        collection)
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import true

import lifemonitor.api.models as models
import lifemonitor.exceptions as lm_exceptions
from lifemonitor import utils as lm_utils
from lifemonitor.api.models import db
from lifemonitor.api.models.registries.registry import WorkflowRegistry
from lifemonitor.api.models.rocrate import ROCrate
from lifemonitor.auth.models import (HostingService, Permission, Resource,
                                     Subscription, User)
from lifemonitor.auth.oauth2.client.models import OAuthIdentity
from lifemonitor.storage import RemoteStorage

# set module level logger
logger = logging.getLogger(__name__)


class Workflow(Resource):
    id = db.Column(db.Integer, db.ForeignKey(Resource.id), primary_key=True)
    public = db.Column(db.Boolean, nullable=True, default=False)

    external_ns = "external-id:"
    _uuidAutoGenerated = True

    __mapper_args__ = {
        'polymorphic_identity': 'workflow'
    }

    def __init__(self, uri=None, uuid=None, identifier=None,
                 version=None, name=None, public=False) -> None:
        super().__init__(uri=uri or f"{self.external_ns}",
                         uuid=uuid, version=version, name=name)
        self.public = public
        self._uuidAutoGenerated = uuid is None
        if identifier is not None:
            self.external_id = identifier

    def __repr__(self):
        return '<Workflow ({}), name: {}>'.format(
            self.uuid, self.name)

    @property
    def _storage(self) -> RemoteStorage:
        return RemoteStorage()

    @hybrid_property
    def external_id(self):
        r = self.uri.replace(self.external_ns, "")
        return r if len(r) > 0 else None

    @external_id.setter
    def external_id(self, value):
        self.uri = f"{self.external_ns}{value}"

    def get_registry_identifier(self, registry: WorkflowRegistry) -> str:
        for version in self.versions.values():
            identifier = version.get_registry_identifier(registry)
            if identifier:
                return identifier
        return None

    @hybrid_property
    def latest_version(self) -> WorkflowVersion:
        return max(self.versions.values(), key=lambda v: v.created)

    def add_version(self, version, uri, submitter: User, uuid=None, name=None):
        return WorkflowVersion(self, uri, version, submitter, uuid=uuid, name=name)

    def remove_version(self, version: WorkflowVersion):
        self.versions.remove(version)

    def get_user_versions(self, user: models.User) -> List[models.WorkflowVersion]:
        return models.WorkflowVersion.query\
            .join(Permission, Permission.resource_id == models.WorkflowVersion.id)\
            .filter(models.WorkflowVersion.workflow_id == self.id)\
            .filter(Permission.user_id == user.id)\
            .all()

    def delete(self):
        super().delete()
        try:
            self._storage.delete_folder(str(self.uuid))
        except Exception as e:
            logger.error(f"Error when deleting ROCrate folder {self.workflow.uuid}")
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception(e)

    def check_health(self) -> dict:
        health = {'healthy': True, 'issues': []}
        for suite in self.test_suites:
            for test_instance in suite.test_instances:
                try:
                    testing_service = test_instance.testing_service
                    if not testing_service.last_test_build.is_successful():
                        health["healthy"] = False
                except lm_exceptions.TestingServiceException as e:
                    health["issues"].append(str(e))
                    health["healthy"] = "Unknown"
        return health

    @classmethod
    def get_public_workflow(cls, uuid) -> Workflow:
        try:
            return cls.query \
                .filter(cls.public == true()) \
                .filter(cls.uuid == lm_utils.uuid_param(uuid)).one()  # noqa: E712
        except NoResultFound as e:
            logger.debug(e)
            return None
        except Exception as e:
            raise lm_exceptions.LifeMonitorException(detail=str(e), stack=str(e))

    @classmethod
    def get_user_workflow(cls, owner: User, uuid) -> Workflow:
        try:
            return cls.query\
                .join(Permission)\
                .filter(Permission.resource_id == cls.id, Permission.user_id == owner.id)\
                .filter(cls.uuid == lm_utils.uuid_param(uuid)).one()
        except NoResultFound as e:
            logger.debug(e)
            return None
        except Exception as e:
            raise lm_exceptions.LifeMonitorException(detail=str(e), stack=str(e))

    @classmethod
    def get_user_workflows(cls, owner: User, include_subscriptions=False) -> List[Workflow]:
        result: List[Workflow] = cls.query.join(Permission)\
            .filter(Permission.user_id == owner.id).all()
        if include_subscriptions:
            subscribed_workflows = cls.query\
                .join(Subscription).filter(Subscription.user_id == owner.id and Subscription.resource_id == cls.id) \
                .filter(cls.public == true()).all()
            user_wf_ids = [w.uuid for w in result]
            result.extend([w for w in subscribed_workflows if w.uuid not in user_wf_ids])
        return result

    @classmethod
    def get_public_workflows(cls) -> List[Workflow]:
        return cls.query\
            .filter(cls.public == true()).all()  # noqa: E712

    @classmethod
    def get_hosted_workflows_by_uri(cls, hosting_service: HostingService, uri: str, submitter: User = None) -> List[Workflow]:
        query = cls.query\
            .join(WorkflowVersion, cls.id == WorkflowVersion.workflow_id)\
            .join(HostingService, WorkflowVersion.hosting_service_id == HostingService.id)\
            .filter(HostingService.uuid == lm_utils.uuid_param(hosting_service.uuid))\
            .filter(WorkflowVersion.uri == uri)
        if submitter:
            query.filter(WorkflowVersion.submitter_id == submitter.id)
        return query.all()


class WorkflowVersionCollection(MappedCollection):

    def __init__(self) -> None:
        super().__init__(lambda wv: wv.workflow.uuid)

    @collection.internally_instrumented
    def __setitem__(self, key, value, _sa_initiator=None):
        current_value = self.get(key, set())
        current_value.add(value)
        super(WorkflowVersionCollection, self).__setitem__(key, current_value, _sa_initiator)

    @collection.internally_instrumented
    def __delitem__(self, key, _sa_initiator=None):
        super(WorkflowVersionCollection, self).__delitem__(key, _sa_initiator)


class WorkflowVersion(ROCrate):
    id = db.Column(db.Integer, db.ForeignKey(ROCrate.id), primary_key=True)
    submitter_id = db.Column(db.Integer, db.ForeignKey(User.id), nullable=True)
    workflow_id = \
        db.Column(db.Integer, db.ForeignKey("workflow.id"), nullable=False)
    workflow = db.relationship("Workflow", foreign_keys=[workflow_id], cascade="all",
                               backref=db.backref("versions", cascade="all, delete-orphan",
                                                  order_by="desc(WorkflowVersion.created)",
                                                  collection_class=attribute_mapped_collection('version')))
    test_suites = db.relationship("TestSuite", back_populates="workflow_version",
                                  cascade="all, delete")
    submitter = db.relationship("User", uselist=False,
                                backref=db.backref("workflows", cascade="all, delete-orphan",
                                                   collection_class=WorkflowVersionCollection))

    roc_link = association_proxy('ro_crate', 'uri')

    __mapper_args__ = {
        'polymorphic_identity': 'workflow_version'
    }

    def __init__(self, workflow: Workflow,
                 uri, version, submitter: User, uuid=None, name=None) -> None:
        super().__init__(uri, uuid=uuid, name=name, version=version)
        self.submitter = submitter
        self.workflow = workflow

    def __repr__(self):
        return '<WorkflowVersion ({}, {}), name: {}, ro_crate link {}>'.format(
            self.uuid, self.version, self.name, self.roc_link)

    @property
    def _storage(self) -> RemoteStorage:
        return RemoteStorage()

    def _get_relative_version(self, delta_index=1) -> Optional[WorkflowVersion]:
        try:
            values = list(self.workflow.versions.values())
            self_index = values.index(self)
            index = self_index + delta_index
            if index >= 0 and index < len(values):
                return values[self_index + delta_index]
        except ValueError:
            message = f"{self} doesn't belong to the workflow {self.workflow}"
            logger.error(message)
            raise lm_exceptions.LifeMonitorException('Value error', detail=message)
        except IndexError:
            pass
        return None

    @property
    def previous_version(self) -> WorkflowVersion:
        return self._get_relative_version(delta_index=1)

    @property
    def next_version(self) -> WorkflowVersion:
        return self._get_relative_version(delta_index=-1)

    def check_health(self) -> dict:
        health = {'healthy': True, 'issues': []}
        for suite in self.test_suites:
            for test_instance in suite.test_instances:
                try:
                    testing_service = test_instance.testing_service
                    if not testing_service.last_test_build.is_successful():
                        health["healthy"] = False
                except lm_exceptions.TestingServiceException as e:
                    health["issues"].append(str(e))
                    health["healthy"] = "Unknown"
        return health

    @property
    def registries(self) -> Set[WorkflowRegistry]:
        return {_.registry for _ in self.registry_workflow_versions.values()} if self.registry_workflow_versions else {}

    def get_registry_identifier(self, registry: WorkflowRegistry) -> str:
        if self.registry_workflow_versions:
            registry_workflow = self.registry_workflow_versions.get(registry.name, None)
            if registry_workflow:
                return registry_workflow.identifier
        return None

    @hybrid_property
    def authorizations(self):
        auths = [a for a in self._authorizations]
        if self.registry_workflow_versions and self.submitter:
            for registry in self.registry_workflow_versions.values():
                for auth in self.submitter.get_authorization(registry.registry):
                    auths.append(auth)
        if self.hosting_service and self.submitter:
            for auth in self.submitter.get_authorization(self.hosting_service):
                auths.append(auth)
        return auths

    # @hybrid_property
    # def roc_link(self) -> str:
    #     return self.uri

    @property
    def workflow_name(self) -> str:
        return self.name or self.main_entity_name or self.dataset_name

    @property
    def is_latest(self) -> bool:
        return self.workflow.latest_version.version == self.version

    @property
    def previous_versions(self) -> List[str]:
        return [w.version for w in self.workflow.versions.values() if w != self and w.created < self.created]

    @property
    def previous_workflow_versions(self) -> List[models.WorkflowVersion]:
        return [w for w in self.workflow.versions.values() if w != self and w.created < self.created]

    @property
    def status(self) -> models.WorkflowStatus:
        return models.WorkflowStatus(self)

    @property
    def is_healthy(self) -> Union[bool, str]:
        return self.check_health()["healthy"]

    def add_test_suite(self, submitter: User,
                       name: str = None, roc_suite: str = None, definition: object = None):
        return models.TestSuite(self, submitter, name=name, roc_suite=roc_suite, definition=definition)

    @property
    def submitter_identity(self):
        # Return the submitter identity wrt the registry
        identity = OAuthIdentity.find_by_user_id(self.submitter.id, self.hosting_service.name)
        return identity.provider_user_id

    def to_dict(self, test_suite=False, test_build=False, test_output=False):
        health = self.check_health()
        data = {
            'uuid': str(self.uuid),
            'version': self.version,
            'name': self.name,
            'roc_link': self.roc_link,
            'isHealthy': health["healthy"],
            'issues': health["issues"]
        }
        if test_suite:
            data['test_suite'] = [s.to_dict(test_build=test_build, test_output=test_output)
                                  for s in self.test_suites]
        return data

    def save(self):
        self.workflow.save(commit=False, flush=False)
        self.modified = self.workflow.modified
        super().save(update_modified=False)

    def delete(self):
        if len(self.workflow.versions) > 1:
            workflow = self.workflow
            self.workflow.remove_version(self)
            workflow.save()
            try:
                self._storage.delete_file(self.storage_path)
            except Exception as e:
                logger.error(f"Error when deleting rocrate archive @ {self.storage_path}")
                if logger.isEnabledFor(logging.DEBUG):
                    logger.exception(e)
        else:
            self.workflow.delete()

    @classmethod
    def all(cls) -> List[WorkflowVersion]:
        return cls.query.all()

    @classmethod
    def get_submitter_versions(cls, submitter: User) -> List[WorkflowVersion]:
        return cls.query.filter(WorkflowVersion.submitter_id == submitter.id).all()

    @classmethod
    def get_public_workflow_version(cls, uuid, version) -> WorkflowVersion:
        try:
            workflow_alias = aliased(Workflow, flat=True)
            return cls.query\
                .join(workflow_alias, workflow_alias.id == cls.workflow_id)\
                .filter(workflow_alias.uuid == lm_utils.uuid_param(uuid))\
                .filter(workflow_alias.public == true())\
                .filter(version == version).one()  # noqa: E712
        except NoResultFound as e:
            logger.debug(e)
            return None
        except Exception as e:
            raise lm_exceptions.LifeMonitorException(detail=str(e), stack=str(e))

    @classmethod
    def get_user_workflow_version(cls, owner: User, uuid, version) -> WorkflowVersion:
        try:
            workflow_alias = aliased(Workflow, flat=True)
            permission_alias = aliased(Permission, flat=True)
            return cls.query\
                .join(workflow_alias, workflow_alias.id == cls.workflow_id)\
                .join(permission_alias, permission_alias.resource_id == cls.id)\
                .filter(workflow_alias.uuid == lm_utils.uuid_param(uuid))\
                .filter(permission_alias.user_id == owner.id)\
                .filter(cls.version == version).one()
        except NoResultFound as e:
            logger.debug(e)
            return None
        except Exception as e:
            raise lm_exceptions.LifeMonitorException(detail=str(e), stack=str(e))

    @classmethod
    def get_user_workflow_versions(cls, owner: User) -> List[WorkflowVersion]:
        return cls.query\
            .join(Permission)\
            .filter(Permission.resource_id == cls.id, Permission.user_id == owner.id).all()

    @classmethod
    def get_hosted_workflow_version(cls, hosting_service: HostingService, uuid, version) -> List[WorkflowVersion]:
        try:
            return cls.query\
                .join(HostingService, cls.hosting_service)\
                .join(Workflow, Workflow.id == cls.workflow_id)\
                .filter(HostingService.uuid == lm_utils.uuid_param(hosting_service.uuid))\
                .filter(Workflow.uuid == lm_utils.uuid_param(uuid))\
                .filter(cls.version == version)\
                .order_by(WorkflowVersion.version.desc()).one()
        except NoResultFound as e:
            logger.debug(e)
            return None
        except Exception as e:
            raise lm_exceptions.LifeMonitorException(detail=str(e), stack=str(e))

    @classmethod
    def get_hosted_workflow_versions(cls, hosting_service: HostingService) -> List[WorkflowVersion]:
        return cls.query\
            .join(HostingService, cls.hosting_service)\
            .filter(HostingService.uuid == lm_utils.uuid_param(hosting_service.uuid))\
            .order_by(WorkflowVersion.version.desc()).all()

    @classmethod
    def get_hosted_workflow_versions_by_uri(cls, hosting_service: HostingService, uri: str) -> List[WorkflowVersion]:
        return cls.query\
            .join(HostingService, cls.hosting_service)\
            .join(WorkflowVersion, WorkflowVersion.hosting_service_id == hosting_service.id)\
            .filter(HostingService.uuid == lm_utils.uuid_param(hosting_service.uuid))\
            .filter(WorkflowVersion.uri == uri).all()
