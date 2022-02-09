
import datetime
import logging

import dramatiq
import flask
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from lifemonitor.api.models.notifications import WorkflowStatusNotification
from lifemonitor.api.models.testsuites.testbuild import BuildStatus
from lifemonitor.api.serializers import BuildSummarySchema
from lifemonitor.auth.models import (EventType, Notification,
                                     UnconfiguredEmailNotification, User)
from lifemonitor.cache import Timeout
from lifemonitor.mail import send_notification

# set module level logger
logger = logging.getLogger(__name__)

# set expiration time (in msec) of tasks
TASK_EXPIRATION_TIME = 30000


def schedule(trigger):
    """
    Decorator to add a scheduled job calling the wrapped function.
    :param  trigger:  an instance of any of the trigger types provided in apscheduler.triggers.
    """
    def decorator(actor):
        app = flask.current_app
        # Check whether the app has a scheduler attribute.
        # When we run as a worker, the app is created but the
        # scheduler is not initialized.
        fn_name = f"{actor.fn.__module__}.{actor.fn.__name__}"
        # We check to see whether the scheduler is available simply by verifying whether the
        # app has the `scheduler` attributed defined.
        # The LM app should have this; the worker app does not have it.
        if hasattr(app, "scheduler"):
            logger.debug("Scheduling function %s with trigger %r", fn_name, trigger)
            flask.current_app.scheduler.add_job(id=fn_name, func=actor.send, trigger=trigger, replace_existing=True)
        else:
            logger.debug("Schedule %s no-op - scheduler not initialized", fn_name)
        return actor
    return decorator


logger.info("Importing task definitions")


@schedule(CronTrigger(second=0))
@dramatiq.actor(max_retries=3, max_age=TASK_EXPIRATION_TIME)
def heartbeat():
    logger.info("Heartbeat!")


@schedule(IntervalTrigger(seconds=Timeout.WORKFLOW * 3 / 4))
@dramatiq.actor(max_retries=3, max_age=TASK_EXPIRATION_TIME)
def check_workflows():
    from flask import current_app
    from lifemonitor.api.controllers import workflows_rocrate_download
    from lifemonitor.api.models import Workflow
    from lifemonitor.auth.services import login_user, logout_user

    logger.info("Starting 'check_workflows' task....")
    for w in Workflow.all():
        try:
            for v in w.versions.values():
                with v.cache.transaction(str(v)):
                    logger.info("Updating external link: %r", v.external_link)
                    u = v.submitter
                    with current_app.test_request_context():
                        try:
                            if u is not None:
                                login_user(u)
                            logger.info("Updating RO-Crate...")
                            workflows_rocrate_download(w.uuid, v.version)
                            logger.info("Updating RO-Crate... DONE")
                        except Exception as e:
                            logger.error(f"Error when updating the workflow {w}: {str(e)}")
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.exception(e)
                        finally:
                            try:
                                logout_user()
                            except Exception as e:
                                logger.debug(e)
        except Exception as e:
            logger.error("Error when executing task 'check_workflows': %s", str(e))
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception(e)
    logger.info("Starting 'check_workflows' task.... DONE!")


@schedule(IntervalTrigger(seconds=Timeout.BUILD * 3 / 4))
@dramatiq.actor(max_retries=3, max_age=TASK_EXPIRATION_TIME)
def check_last_build():
    from lifemonitor.api.models import Workflow

    logger.info("Starting 'check_last build' task...")
    for w in Workflow.all():
        try:
            latest_version = w.latest_version
            for s in latest_version.test_suites:
                logger.info("Updating workflow: %r", w)
                for i in s.test_instances:
                    with i.cache.transaction(str(i)):
                        builds = i.get_test_builds(limit=10)
                        logger.info("Updating latest builds: %r", builds)
                        for b in builds:
                            logger.info("Updating build: %r", i.get_test_build(b.id))
                        last_build = i.last_test_build
                        # check state transition
                        failed = last_build.status == BuildStatus.FAILED
                        if len(builds) == 1 and failed or \
                                builds[0].status in (BuildStatus.FAILED, BuildStatus.PASSED) and \
                                builds[1].status in (BuildStatus.FAILED, BuildStatus.PASSED) and \
                                len(builds) > 1 and builds[1].status != last_build.status:
                            logger.info("Updating latest build: %r", last_build)
                            notification_name = f"{last_build} {'FAILED' if failed else 'RECOVERED'}"
                            if len(Notification.find_by_name(notification_name)) == 0:
                                users = latest_version.workflow.get_subscribers()
                                n = WorkflowStatusNotification(
                                    EventType.BUILD_FAILED if failed else EventType.BUILD_RECOVERED,
                                    notification_name,
                                    {'build': BuildSummarySchema(exclude_nested=False).dump(last_build)},
                                    users)
                                n.save()
        except Exception as e:
            logger.error("Error when executing task 'check_last_build': %s", str(e))
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception(e)
    logger.info("Checking last build: DONE!")


@schedule(IntervalTrigger(seconds=60))
@dramatiq.actor(max_retries=0, max_age=TASK_EXPIRATION_TIME)
def send_email_notifications():
    notifications = [n for n in Notification.not_emailed()
                     if not isinstance(n, UnconfiguredEmailNotification)]
    logger.info("Found %r notifications to send by email", len(notifications))
    count = 0
    for n in notifications:
        logger.debug("Processing notification %r ...", n)
        recipients = [
            u.user.email for u in n.users
            if u.emailed is None and u.user.email_notifications_enabled and u.user.email
        ]
        sent = send_notification(n, recipients=recipients)
        logger.debug("Notification email sent: %r", sent is not None)
        if sent:
            logger.debug("Notification '%r' sent by email @ %r", n.id, sent)
            for u in n.users:
                if u.user.email in recipients:
                    u.emailed = sent
            n.save()
            count += 1
        logger.debug("Processing notification %r ... DONE", n)
    logger.info("%r notifications sent by email", count)
    return count


@schedule(CronTrigger(minute=0, hour=1))
@dramatiq.actor(max_retries=0, max_age=TASK_EXPIRATION_TIME)
def cleanup_notifications():
    logger.info("Starting notification cleanup")
    count = 0
    current_time = datetime.datetime.utcnow()
    one_week_ago = current_time - datetime.timedelta(days=0)
    notifications = Notification.older_than(one_week_ago)
    for n in notifications:
        try:
            n.delete()
            count += 1
        except Exception as e:
            logger.debug(e)
            logger.error("Error when deleting notification %r", n)
    logger.info("Notification cleanup completed: deleted %r notifications", count)


@schedule(IntervalTrigger(seconds=60))
@dramatiq.actor(max_retries=0, max_age=TASK_EXPIRATION_TIME)
def check_email_configuration():
    logger.info("Check for users without notification email")
    count = 0
    users = []
    try:
        for u in User.all():
            if not u.email and len(UnconfiguredEmailNotification.find_by_user(u)) == 0:
                users.append(u)
                count += 1
        if len(users) > 0:
            n = UnconfiguredEmailNotification(
                "Unconfigured email",
                users=users)
            n.save()
    except Exception as e:
        logger.debug(e)
        logger.error("Error when deleting notification %r", n)
    logger.info("Check for users without notification email configured: generated notification for %r users", count)
