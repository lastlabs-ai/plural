"""A Harness that restocks and reorders by fixed rules instead of calling a model."""

import re

from plural import Harness, HarnessResult

PRODUCTS = ("candy", "chips", "soda", "water")
SLOT_CAPACITY = 40


class RestockRules(Harness):
    auth = ("none",)

    def run(self, task, agent, environment):
        """Play day after day, reading only what the Environment shows, until the run ends."""
        environment.reset()
        config = self.config
        days = 0
        while True:
            machine = self._counts(environment.step("machine_status").observation, "in the machine")
            storage_text = self._text(environment.step("storage_status").observation)
            storage = self._counts(storage_text, "in storage")
            on_order = self._on_order(storage_text)
            for product in PRODUCTS:
                if machine[product] < config["restock_below"] and storage[product] > 0:
                    environment.step(
                        "restock", product=product, units=SLOT_CAPACITY - machine[product]
                    )
                    storage[product] -= min(storage[product], SLOT_CAPACITY - machine[product])
                if storage[product] + on_order[product] < config["reorder_point"]:
                    environment.step(
                        "order",
                        supplier=config["supplier"],
                        product=product,
                        units=config["order_units"],
                    )
            result = environment.step("wait")
            days += 1
            if result.terminated or result.truncated:
                return HarnessResult(response=f"Ran {days} days.")

    @staticmethod
    def _text(observation):
        return observation.get("text", "") if isinstance(observation, dict) else str(observation)

    def _counts(self, observation, where):
        text = self._text(observation)
        counts = dict.fromkeys(PRODUCTS, 0)
        for product, units in re.findall(rf"(\w+): (\d+) {where}", text):
            if product in counts:
                counts[product] = int(units)
        return counts

    @staticmethod
    def _on_order(text):
        counts = dict.fromkeys(PRODUCTS, 0)
        for units, product in re.findall(r"On order: (\d+) (\w+)", text):
            if product in counts:
                counts[product] += int(units)
        return counts
