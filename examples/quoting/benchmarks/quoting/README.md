# quoting

Eighty requests for quote to a steel mill, in four categories:

| Category | Tasks | The right answer |
| --- | --- | --- |
| Simple | 32 | A quote at today's price for the date the customer asked for. Some order in hundredweight, and four ask for a price below the mill's cost. |
| Rush | 22 | A quote whose date is the earliest the mill can meet, because the date asked for is too early. |
| Ambiguous | 13 | A handoff: the grade or the quantity isn't settled. |
| Out of stock | 13 | A handoff: too little on hand, or a grade the mill doesn't sell. |

A Trial scores 1 when `quote-check` passes every check that applies and 0 otherwise. The
checks are its sub-scores: `decision_correct` (quoted or handed off as the answer key
says), and for a quote, `price_correct` (the right grade and tons at the last price
looked up, with the total to the cent), `delivery_feasible`, and `above_cost`.
`margin_usd` is reported beside them and never affects the score.
