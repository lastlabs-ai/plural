# vending

A vending machine with four products (candy, chips, soda, water), run a day at a
time on a clock that counts days.

## Apps

- **machine**: `machine_status`, `set_price`, `restock`. Each slot holds 40 units.
  Every day closes on its own: seeded customers buy what is in the machine, fewer at
  weekends and in winter, and fewer as a price rises above the list price. The $16
  location fee is paid from the bank.
- **storage**: `storage_status`. Deliveries arrive here; `restock` moves stock from
  here into the machine.
- **bank**: `bank_balance`. Sales go in; fees and orders come out. An order the bank
  can't pay for is declined.
- **suppliers**: `email` and `order`, each by the supplier's account name. Two
  wholesalers answer email as personas (`plural.sim.Persona`): one delivers the next
  day at higher prices, the other in three days, cheaper, with a 50-unit minimum. Their
  account names are in the Task. With no gateway key for personas, each answers from a
  script with its price list.

## Time

`wait` runs the world to the next event: the day's close, or a delivery. Every
observation starts with the day, such as `[Day 41]`. The episode ends when the Task's
days are up, or at the 365-day horizon.

## State and metrics

Net worth is cash, plus stock in the machine, in storage, and on order, each unit at
the lowest supplier price. The `vending-books` Verifier measures it every day.
