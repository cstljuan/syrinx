"""Tool schemas: what the model reads to decide when to call Kairos."""

KAIROS_PARK = {
    "name": "kairos_park",
    "description": (
        "Park a question for the user instead of asking it now. Use this while Kairos reports that the "
        "user is in a focus block: record the question, the default you will proceed with, and why. "
        "Then continue the task with that default. The user answers every parked question in one pass "
        "when they return."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question, as you would ask the user."},
            "default": {"type": "string", "description": "The answer you are proceeding with for now."},
            "why": {"type": "string", "description": "One line on why you need it and why the default is safe."},
        },
        "required": ["question", "default"],
    },
}

KAIROS_INTERRUPT = {
    "name": "kairos_interrupt",
    "description": (
        "Declare that the task cannot move at all without the user's answer, even though they are in a "
        "focus block. Use it rarely: it counts as an interruption. After it succeeds, ask the question "
        "with clarify as usual; Kairos lets that one clarify through."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The blocking question."},
            "why": {"type": "string", "description": "Why no default is safe."},
        },
        "required": ["question", "why"],
    },
}

KAIROS_STATUS = {
    "name": "kairos_status",
    "description": (
        "Read the user's Kairos state: whether a focus block is active and until when, whether it is past "
        "their cutoff, and how many questions are parked. Call it when you need to know whether the user is "
        "reachable right now."
    ),
    "parameters": {"type": "object", "properties": {}},
}
