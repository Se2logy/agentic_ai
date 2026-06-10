"""State enum and state definitions for the guest check-in workflow."""

from enum import Enum


class State(str, Enum):
    """All possible states in the guest check-in flow.

    Inherits from str so it serialises cleanly to JSON / DB columns.
    """

    INIT = "INIT"
    PRIVACY_POLICY_PENDING = "PRIVACY_POLICY_PENDING"
    HOUSE_RULES_PENDING = "HOUSE_RULES_PENDING"
    RENTAL_AGREEMENT_PENDING = "RENTAL_AGREEMENT_PENDING"
    INFO_VERIFY_PENDING = "INFO_VERIFY_PENDING"
    ID_VERIFY_PENDING = "ID_VERIFY_PENDING"
    INCIDENTAL_PROTECTION_PENDING = "INCIDENTAL_PROTECTION_PENDING"
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"


STATE_INFO: dict[State, dict[str, str | list[str]]] = {
    State.INIT: {
        "required_action": "Initialize check-in session",
        "valid_intents": ["start"],
        "on_enter": "Session created, ready to begin onboarding",
        "description": "Session has been created but onboarding has not started yet.",
    },
    State.PRIVACY_POLICY_PENDING: {
        "required_action": "Accept or decline the Privacy Policy & Data Usage agreement",
        "valid_intents": ["agree", "decline"],
        "on_enter": "Agent presents privacy policy text to the guest",
        "description": "Guest must review and respond to the privacy policy.",
    },
    State.HOUSE_RULES_PENDING: {
        "required_action": "Accept or decline the House Rules",
        "valid_intents": ["agree", "decline"],
        "on_enter": "Agent presents house rules text to the guest",
        "description": "Guest must review and respond to the house rules.",
    },
    State.RENTAL_AGREEMENT_PENDING: {
        "required_action": "Accept or decline the Rental Agreement",
        "valid_intents": ["agree", "decline"],
        "on_enter": "Agent presents rental agreement text to the guest",
        "description": "Guest must review and respond to the rental agreement.",
    },
    State.INFO_VERIFY_PENDING: {
        "required_action": "Confirm personal information (name, email, phone, number of guests)",
        "valid_intents": ["confirm", "provide_info"],
        "on_enter": "Agent retrieves and presents reservation information for verification",
        "description": "Guest must verify or correct their personal information.",
    },
    State.ID_VERIFY_PENDING: {
        "required_action": "Upload government-issued ID via the secure link",
        "valid_intents": ["upload_id"],
        "on_enter": "Agent generates and sends a secure upload link to the guest",
        "description": "Guest must upload a government-issued ID document.",
    },
    State.INCIDENTAL_PROTECTION_PENDING: {
        "required_action": "Select Damage Waiver or Security Hold and complete payment",
        "valid_intents": ["select_option"],
        "on_enter": "Agent generates and sends selection + payment link to the guest",
        "description": "Guest must choose incidental protection and complete payment.",
    },
    State.COMPLETED: {
        "required_action": "None — onboarding finished",
        "valid_intents": [],
        "on_enter": "Generate arrival instructions and send to guest",
        "description": "All onboarding steps have been completed successfully.",
    },
    State.REFUSED: {
        "required_action": "Guest declined an agreement; onboarding halted",
        "valid_intents": ["resume"],
        "on_enter": "Record refusal and halt onboarding",
        "description": "Guest declined an agreement. Onboarding can be restarted from the beginning.",
    },
}
