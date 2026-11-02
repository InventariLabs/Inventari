/**
 * The states a request is still waiting on a decision in.
 *
 * One constant because three places have to agree: the dashboard's default
 * tab, the action-item badge, and the link the backend puts in its approver
 * notification (``_services_notify.QUEUE_LINK``). They did not — the badge
 * counted PENDING only and undercounted every multi-stage request in flight.
 */
export const OPEN_APPROVAL_STATES = "PENDING,IN_PROGRESS";
