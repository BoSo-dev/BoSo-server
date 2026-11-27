from app.modules.policies.schemas import EligibilityRules
from app.modules.todos.schemas import EligibilityResult
from app.modules.users.schemas import PersonalizationContext


def evaluate_eligibility(rules: EligibilityRules, profile: PersonalizationContext):
    missing, denied = [], []
    if rules.age_min is not None or rules.age_max is not None:
        if profile.age is None:
            missing.append("age")
        elif (rules.age_min is not None and profile.age < rules.age_min) or (
            rules.age_max is not None and profile.age > rules.age_max
        ):
            denied.append("age")
    for field, expected, actual in (
        ("region_code", rules.region_codes, [profile.region_code] if profile.region_code else []),
        ("transport_cards", rules.transport_cards, profile.transport_cards),
        ("transport_modes", rules.transport_modes, profile.transport_modes),
    ):
        if not expected:
            continue
        if not actual or (field == "transport_cards" and "other_or_none" in actual):
            missing.append(field)
        elif not set(expected).intersection(actual):
            denied.append(field)
    if denied:
        return EligibilityResult(state="not_eligible", reasons=denied)
    if rules.requires_confirmation or rules.additional_requirements:
        missing.append("additional_confirmation")
    return EligibilityResult(state="unknown" if missing else "eligible", reasons=missing)
