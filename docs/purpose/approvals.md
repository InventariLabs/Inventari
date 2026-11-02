# Approvals

## Job
"Make sure certain things do not happen until somebody who is allowed to has said so — and that it
is afterwards clear who said it."

## Whose job
A manager configures the workflows and decides; anyone whose work is blocked raises the request,
usually without ever opening this module's own screens.

## Inside the boundary
Workflow definitions per registered target type, their stages and who may decide at each; whether a
workflow is in force — it is saved switched off unless the caller asks otherwise, and the screen
switches it on only after saying what it will hold, refusing if that has changed since (the API
asks the same of every caller whose target type has a scope to show: switching a workflow on, by PATCH or by creating it on, needs the
`expected_scope` it was shown, read from the workflow list, and is answered 422 without it); whose submissions it holds — everyone, or the people and roles
it names; the queue of what is waiting; the decision and its record. And telling people: the
deciders of a stage when a request reaches it (in the app and by mail); the requester when it is
rejected (in the app and by mail), or closed because its workflow went off (in the app only); the
requester and the administrators when a stage has nobody left who can decide (in the app and by
mail). Each reader gets it in their own language.

## Outside the boundary
**Which operations need consent at all.** That is the asking module's decision, always — approvals
answers *how*, never *when* (AGENTS.md, approval workflow integration). Even the sentence "this
workflow will hold every confirmed document" is the asking module's, through the scope provider it
registers; approvals only shows it.

## Own concepts / Borrowed
**Own:** Workflow, stage, ApprovalRequest, target type, decision.
**Borrowed:** the identity of whatever is being approved — approvals never reads the other module's
tables, only the reference it was handed.

## Deliberately not done
- **No approval of anything a module has not registered.** There is no "approve this arbitrary
  thing" screen; a target type is code, not a form.
- **No delegation, no out-of-office, no escalation timers.** Whoever may decide, decides.
- **No delivery of its own.** It writes what the message says; the notification subsystem and the
  installation's mail carry it, and a failure there never fails the request.
- **No retrospective approval.** A decision applies to a pending request, not to something already
  done.

## Switched off
Every consumer must keep working: `check_and_block()` becomes a no-op, and operations that would
have waited simply proceed. A module that crashes or hides its action when approvals is off has
broken the contract, not the other way round.
