# Rentals

## Job
"Promise a thing for a window, hand it out when the window starts, take it back when it
ends — and show at a glance what is late, what goes out today and what cannot be booked."

## Whose job
The person at the desk hands equipment out and takes it back; whoever plans the week reserves
it; a manager sets the buffers between bookings and blocks a unit for service. A borrower never
opens the module: they hold a thing, not a screen.

## Inside the boundary
Bookings with a window, a borrower and lines (one asset, or a model and a count); availability
per asset and per model, with the buffer hours a model or a category needs before and after a
booking; manual and service blocks; pickup and return, which reach the equipment register's
check-out and check-in through its public API, never its services; extending a booking when the
time is free; the derived overdue state and a today view of pickups, returns and late loans; a
calendar grouped by model with an "any unit" row for bookings not yet resolved to a unit.

## Outside the boundary
**What an asset is, and who holds it.** The equipment module owns the register, the status
machine, the hand-out record and the return condition; rentals says *when* a thing is promised
and asks equipment to hand it out. **Money** — prices, deposits, late fees, agreements — is
step 3, not this module. **Kits and borrowers without accounts** are step 2.

## Own concepts / Borrowed
**Own:** booking, booking line, the unit a line resolves to, block, buffer rule, availability.
**Borrowed:** the asset and its model, serial and category (from `equipment_api`); the partner or
member who borrows (from CoreAPI); the hand-out itself (equipment's assignment).

## Deliberately not done
- **No stored "late" status.** A booking is late when its window has passed and it has not come
  back; the state is read, so no job can leave it disagreeing with the clock.
- **No partial pickup or partial return in this step.** A pickup is confirmed only when every
  line is scanned or chosen; a return lists every unit. Step 2 adds partial return.
- **No overbooking.** Two requests for one asset and an overlapping window cannot both succeed:
  the check and the write share one transaction under an advisory lock.

## Switched off
The equipment module must stay on: a booking has nothing to hand out without it. With rentals
switched off, equipment keeps working exactly as before — its assignments are not bookings, and
nothing in the register depends on this module's tables.
