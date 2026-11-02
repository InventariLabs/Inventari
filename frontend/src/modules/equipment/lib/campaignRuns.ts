import type { TFunction } from "i18next";
import { toast } from "sonner";
import type {
  LaunchResult,
  ReminderRunResult,
} from "@/modules/equipment/api/equipment_campaigns";

/**
 * Tell the person who pressed Send Reminders what came of it.
 *
 * The button used to answer `{reminders_sent: 0}` with an unchanged page, and
 * the admin believed the people had been chased. A run that sent nothing now
 * says why — nobody is left to ask, there is no outgoing e-mail, everyone was
 * reminded within the day — and a run that sent some says how many.
 */
export function announceReminderRun(t: TFunction, run: ReminderRunResult) {
  const notDelivered = run.not_delivered ?? 0;
  if (run.reminders_sent > 0) {
    toast.success(
      t("equipment:attestation.reminders.sent", { count: run.reminders_sent }),
      notDelivered > 0
        ? {
            description: t("equipment:attestation.reminders.someNotDelivered", {
              count: notDelivered,
            }),
          }
        : undefined,
    );
    return;
  }
  if ((run.awaiting_reply ?? 0) === 0) {
    toast.info(t("equipment:attestation.reminders.nobodyWaiting"));
  } else if (run.email_unavailable) {
    toast.warning(t("equipment:attestation.reminders.noEmail"));
  } else if ((run.reminded_recently ?? 0) >= run.awaiting_reply) {
    toast.info(t("equipment:attestation.reminders.remindedRecently"));
  } else {
    toast.error(t("equipment:attestation.reminders.notDelivered"));
  }
}

/**
 * Tell the person who launched a campaign who was asked and who was not.
 *
 * The launch used to end on silence. Holders without an e-mail address were
 * left out without a word, and an organization that sends no mail had its
 * whole campaign go nowhere while the dialog had promised an e-mail to
 * everyone. Their links are on the campaign page, to hand over in person.
 */
export function announceLaunch(t: TFunction, run: LaunchResult) {
  const skipped = run.skipped_people ?? [];
  const skippedLine =
    skipped.length > 0
      ? t("equipment:attestation.launchResult.skipped", {
          names: skipped.join(", "),
        })
      : undefined;
  if (run.email_unavailable) {
    toast.warning(t("equipment:attestation.launchResult.noEmail"), {
      description: skippedLine,
    });
    return;
  }
  toast.success(
    t("equipment:attestation.launchResult.sent", { count: run.emails_sent }),
    skippedLine || run.emails_failed > 0
      ? {
          description: [
            skippedLine,
            run.emails_failed > 0
              ? t("equipment:attestation.launchResult.failed", {
                  count: run.emails_failed,
                })
              : undefined,
          ]
            .filter(Boolean)
            .join(" "),
        }
      : undefined,
  );
}
