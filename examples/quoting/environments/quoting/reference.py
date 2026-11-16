"""The quoting desk's reference policy: what a careful person at the desk would do.

`plural task check` plays it on every Task through the normal engine, so a Task
whose reference fails has a broken Task or a broken grader, not a weak Agent. It
reads only what an Agent reads, the request and each action's reply, never the
answer key.
"""

import json
import re
from datetime import date

GRADES = {
    "A36": r"\bA36\b",
    "A572-50": r"\bA572(?:-50| Grade 50)\b",
    "A516-70": r"\bA516-70\b",
    "A500-B": r"\bA500(?:-B| Grade B)\b",
    "1018": r"\b1018\b",
    "304SS": r"\b304(?:SS| stainless)\b",
}
QUANTITY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(short tons|tons|cwt)\b", re.IGNORECASE)
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MONEY = re.compile(r"\$([\d,]+\.\d{2})")


def solve(task, environment):
    """Answer one request for quote: quote it from the mill's figures, or hand it off."""
    environment.reset()
    request = task.instructions
    grades = [grade for grade, pattern in GRADES.items() if re.search(pattern, request)]
    quantities = QUANTITY.findall(request)
    if len(grades) != 1 or len(quantities) != 1 or "between" in request.lower():
        return _handoff(environment, "The grade or the quantity isn't settled; please confirm.")
    grade = grades[0]
    amount, unit = quantities[0]
    tons = float(amount.replace(",", ""))
    if unit.lower() == "cwt":
        tons /= 20
    stock = _text(environment.step("check_stock", grade=grade, tons=tons))
    if "not enough" in stock:
        return _handoff(environment, f"Not enough {grade} on hand for {tons:g} short tons.")
    price = float(
        MONEY.search(_text(environment.step("lookup_price", grade=grade))).group(1).replace(",", "")
    )
    earliest = DATE.search(_text(environment.step("check_schedule", tons=tons))).group(0)
    requested = DATE.search(request)
    delivery = max(earliest, requested.group(0)) if requested else earliest
    date.fromisoformat(delivery)
    environment.step(
        "submit_quote",
        grade=grade,
        tons=tons,
        price_per_ton=price,
        total_price=round(price * tons, 2),
        delivery_date=delivery,
        notes=f"{tons:g} short tons of {grade} at ${price:,.2f} per ton, delivered {delivery}.",
    )
    return f"Quoted {tons:g} t of {grade}."


def _handoff(environment, reason):
    environment.step("handoff", reason=reason)
    return reason


def _text(step):
    observation = step.observation
    if isinstance(observation, str):
        return observation
    if isinstance(observation, dict) and isinstance(observation.get("text"), str):
        return observation["text"]
    return json.dumps(observation, default=str)
