from __future__ import annotations

import logging
import lifemonitor.api.models as models
import lifemonitor.common as common


# set module level logger
logger = logging.getLogger(__name__)


class AggregateTestStatus:
    ALL_PASSING = "all_passing"
    SOME_PASSING = "some_passing"
    ALL_FAILING = "all_failing"
    NOT_AVAILABLE = "not_available"


class Status:

    def __init__(self) -> None:
        self._status = AggregateTestStatus.NOT_AVAILABLE
        self._latest_builds = None
        self._availability_issues = None

    @property
    def aggregated_status(self):
        return self._status

    @property
    def latest_builds(self):
        return self._latest_builds.copy()

    @property
    def availability_issues(self):
        return self._availability_issues.copy()

    @staticmethod
    def _update_status(current_status, build_passing):
        status = current_status
        if status == AggregateTestStatus.NOT_AVAILABLE:
            if build_passing:
                status = AggregateTestStatus.ALL_PASSING
            elif not build_passing:
                status = AggregateTestStatus.ALL_FAILING
        elif status == AggregateTestStatus.ALL_PASSING:
            if not build_passing:
                status = AggregateTestStatus.SOME_PASSING
        elif status == AggregateTestStatus.ALL_FAILING:
            if build_passing:
                status = AggregateTestStatus.SOME_PASSING
        return status

    @staticmethod
    def check_status(suites):
        status = AggregateTestStatus.NOT_AVAILABLE
        latest_builds = []
        availability_issues = []

        if len(suites) == 0:
            availability_issues.append({
                "issue": "No test suite configured for this workflow"
            })

        for suite in suites:
            if len(suite.test_instances) == 0:
                availability_issues.append({
                    "issue": f"No test instances configured for suite {suite}"
                })
            for test_instance in suite.test_instances:
                try:
                    latest_build = test_instance.last_test_build
                    if latest_build is None:
                        availability_issues.append({
                            "service": test_instance.testing_service.url,
                            "test_instance": test_instance,
                            "issue": "No build found"
                        })
                    else:
                        latest_builds.append(latest_build)
                        status = WorkflowStatus._update_status(status, latest_build.is_successful())
                except common.TestingServiceException as e:
                    availability_issues.append({
                        "service": test_instance.testing_service.url,
                        "resource": test_instance.resource,
                        "issue": str(e)
                    })
                    logger.exception(e)
        # update the current status
        return status, latest_builds, availability_issues


class WorkflowStatus(Status):

    def __init__(self, workflow: models.Workflow) -> None:
        self.workflow = workflow
        self._status, self._latest_builds, self._availability_issues = WorkflowStatus.check_status(self.workflow.test_suites)


class SuiteStatus(Status):

    def __init__(self, suite: models.TestSuite) -> None:
        self.suite = suite
        self._status, self._latest_builds, self._availability_issues = Status.check_status([suite])
