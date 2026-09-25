"""Distinguish an accepted long-running command from an observed result."""

PENDING_ACTIONS = frozenset({
    "follow_player", "goto", "explore", "set_adventure", "go_base",
    "find_biome", "find_resource", "mine", "attack_entity", "hunt",
    "collect_for_item",
})


def normalize_action_status(status: str, action: str) -> str:
    if status in {"planner_ok", "command_ok"} and action in PENDING_ACTIONS:
        return status.replace("_ok", "_accepted")
    return status
