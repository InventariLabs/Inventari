# Core — Announcements

## Job
"Tell me something about this installation that I could not have worked out from my own data."

## Whose job
Everyone reads. Whoever runs the server writes — an operational note, a new version, a module that
has just arrived — through the API as the installation's superuser. There is no screen for writing
one, and nothing writes one on its own.

## Inside the boundary
A banner in the global notification slot, and remembering which ones a person has dismissed — in
that browser only, so another device, or cleared site data, shows them again.

The same frontend area also carries the notification tray, a person's own notifications. The tray
lives here; the notifications themselves belong to the notification subsystem.

## Outside the boundary
Anything about the user's own records. "This product expires tomorrow" is not an announcement; it
belongs to the module that owns the product.

## Own concepts / Borrowed
**Own:** Announcement.
**Borrowed:** the notification slot it renders into; the notifications its tray lists.

## Deliberately not done
- **No messaging between people.** No recipients, no replies, no threads.
- **No email.** Reaching somebody who is not looking at the app is the notification subsystem's job.
- **No targeting by role or module.** An announcement is about the installation, so it is for
  everyone in it.

## Switched off
It is always on and has no tile of its own. With nothing to announce it must render nothing at all —
an empty banner across the top of every screen is a defect.
