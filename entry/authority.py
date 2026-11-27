"""Resolve one action against a protection applying to the same change."""
from dataclasses import dataclass

LOW, NORMAL, HIGH, HIGHEST = -1, 0, 1, 2
AUTHORITY = {"较低话语权": LOW, "常规": NORMAL, "常规话语权": NORMAL,
             "较高话语权": HIGH, "最高话语权": HIGHEST,
             "low": LOW, "normal": NORMAL, "high": HIGH, "highest": HIGHEST}


def rank(value):
    original = value
    if isinstance(value, str):
        value = AUTHORITY.get(value)
    if type(value) is not int or value not in (LOW, NORMAL, HIGH, HIGHEST):
        raise ValueError(f"未知的话语权 {original!r}")
    return value


def player_of(owner):
    card = getattr(owner, "card", None)
    return getattr(card if card is not None else owner, "player", None)


@dataclass(frozen=True)
class Action:
    authority: int
    player: object
    first_player: object

    def overcomes(self, protection, defender):
        if self.authority != protection:
            return self.authority > protection
        return (protection == HIGHEST and self.player is not None
                and self.player is self.first_player and defender is not None
                and self.player is not defender)

    def disables(self, authority, defender, *, protected=False):
        # Ordinary effects have no implicit same-rank immunity to blanking.
        if self.authority == authority and not protected and authority != HIGHEST:
            return True
        return self.overcomes(authority, defender)


def action_by(owner, authority=NORMAL):
    player = player_of(owner)
    return Action(authority, player, getattr(getattr(player, "game", None), "first_player", None))


# Rank belongs to the named rule on a face. Numeric damage is not a ranked trait.
CARD_TRAITS = {"ignore_range": True, "opponent_range_reduction": False,
               "protect_range_level": True, "preserve_pre_reveal_target": True}
DIE_TRAITS = {"ignore_range": True, "clash_order": False}


def trait_rank(data, key):
    return rank(data.get("trait_authority", {}).get(key, NORMAL))


def printed_traits(face, traits):
    for key, protected in traits.items():
        active = face.get(key) or face.get(key + "_amount")
        if active and (key != "clash_order" or active == "lower"):
            yield trait_rank(face, key), protected


def validate_trait_authority(data, allowed):
    ranks = data.get("trait_authority", {})
    if not isinstance(ranks, dict) or ranks.keys() - allowed.keys():
        raise ValueError("话语权须指向适用的词条属性")
    for key in ranks:
        if key not in data and key + "_amount" not in data:
            raise ValueError(f"话语权缺少对应属性 {key!r}")
        trait_rank(data, key)


def printed_entries(specs):
    for spec in specs:
        if isinstance(spec, dict) and "entries" in spec and "trigger" not in spec:
            yield from printed_entries(spec["entries"])
        else:
            yield spec


def printed_power(spec):
    if not isinstance(spec, dict):
        return NORMAL, False
    return rank(spec.get("authority", NORMAL)), spec_protection(spec)


def spec_protection(spec):
    trigger = spec.get("trigger", "")
    name = getattr(trigger, "name", trigger)
    # Cancelling an absorption or invalidating an entry challenges its holder.
    target = str(name).removeprefix("BEFORE ")
    is_guard = spec.get("operation") == {"op": "cancel"} and target not in ("ENTRY", "SHIELD_ABSORB")
    value = spec.get("protection", is_guard)
    if type(value) is not bool:
        raise ValueError("保护词条标记须为布尔值")
    return value
