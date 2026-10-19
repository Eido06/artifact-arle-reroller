# rotations.py

# Maximum 100%-tier single roll values for 5-star artifacts
STAT_MAX = {
    "CR": 0.0389,
    "CD": 0.0777,
    "ATK_PCT": 0.0583,
    "FLAT_ATK": 19.45,
    "EM": 23.31,
    "DEAD": 0.0
}

TIERS = [0.7, 0.8, 0.9, 1.0]

# Maps Enka appendPropId strings to internal stat keys
ENKA_PROP_MAP = {
    "FIGHT_PROP_CRITICAL": ("CR", True),          # True = Percentage stat
    "FIGHT_PROP_CRITICAL_HURT": ("CD", True),
    "FIGHT_PROP_ATTACK_PERCENT": ("ATK_PCT", True),
    "FIGHT_PROP_ATTACK": ("FLAT_ATK", False),     # False = Flat stat
    "FIGHT_PROP_ELEMENT_MASTERY": ("EM", False),
    "FIGHT_PROP_HP": ("DEAD", False),
    "FIGHT_PROP_HP_PERCENT": ("DEAD", True),
    "FIGHT_PROP_DEFENSE": ("DEAD", False),
    "FIGHT_PROP_DEFENSE_PERCENT": ("DEAD", True),
    "FIGHT_PROP_CHARGE_EFFICIENCY": ("DEAD", True),
}

# Friendly labels for dead stats so the CLI shows the exact substat name
PROP_DISPLAY_NAME = {
    "FIGHT_PROP_CRITICAL": "CRIT Rate",
    "FIGHT_PROP_CRITICAL_HURT": "CRIT DMG",
    "FIGHT_PROP_ATTACK_PERCENT": "ATK%",
    "FIGHT_PROP_ATTACK": "Flat ATK",
    "FIGHT_PROP_ELEMENT_MASTERY": "Elemental Mastery",
    "FIGHT_PROP_HP": "Flat HP",
    "FIGHT_PROP_HP_PERCENT": "HP%",
    "FIGHT_PROP_DEFENSE": "Flat DEF",
    "FIGHT_PROP_DEFENSE_PERCENT": "DEF%",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "Energy Recharge",
}

# Exact 5-star artifact substat roll ID table (used to extract +0 base rolls from Enka)
SUBSTAT_ROLL_IDS = {
    501021: ("FIGHT_PROP_HP", 209.13), 501022: ("FIGHT_PROP_HP", 239.00),
    501023: ("FIGHT_PROP_HP", 268.88), 501024: ("FIGHT_PROP_HP", 298.75),
    501031: ("FIGHT_PROP_HP_PERCENT", 4.08), 501032: ("FIGHT_PROP_HP_PERCENT", 4.66),
    501033: ("FIGHT_PROP_HP_PERCENT", 5.25), 501034: ("FIGHT_PROP_HP_PERCENT", 5.83),
    501051: ("FIGHT_PROP_ATTACK", 13.62), 501052: ("FIGHT_PROP_ATTACK", 15.56),
    501053: ("FIGHT_PROP_ATTACK", 17.51), 501054: ("FIGHT_PROP_ATTACK", 19.45),
    501061: ("FIGHT_PROP_ATTACK_PERCENT", 4.08), 501062: ("FIGHT_PROP_ATTACK_PERCENT", 4.66),
    501063: ("FIGHT_PROP_ATTACK_PERCENT", 5.25), 501064: ("FIGHT_PROP_ATTACK_PERCENT", 5.83),
    501081: ("FIGHT_PROP_DEFENSE", 16.20), 501082: ("FIGHT_PROP_DEFENSE", 18.52),
    501083: ("FIGHT_PROP_DEFENSE", 20.83), 501084: ("FIGHT_PROP_DEFENSE", 23.15),
    501091: ("FIGHT_PROP_DEFENSE_PERCENT", 5.10), 501092: ("FIGHT_PROP_DEFENSE_PERCENT", 5.83),
    501093: ("FIGHT_PROP_DEFENSE_PERCENT", 6.56), 501094: ("FIGHT_PROP_DEFENSE_PERCENT", 7.29),
    501201: ("FIGHT_PROP_CRITICAL", 2.72), 501202: ("FIGHT_PROP_CRITICAL", 3.11),
    501203: ("FIGHT_PROP_CRITICAL", 3.50), 501204: ("FIGHT_PROP_CRITICAL", 3.89),
    501221: ("FIGHT_PROP_CRITICAL_HURT", 5.44), 501222: ("FIGHT_PROP_CRITICAL_HURT", 6.22),
    501223: ("FIGHT_PROP_CRITICAL_HURT", 6.99), 501224: ("FIGHT_PROP_CRITICAL_HURT", 7.77),
    501231: ("FIGHT_PROP_CHARGE_EFFICIENCY", 4.53), 501232: ("FIGHT_PROP_CHARGE_EFFICIENCY", 5.18),
    501233: ("FIGHT_PROP_CHARGE_EFFICIENCY", 5.83), 501234: ("FIGHT_PROP_CHARGE_EFFICIENCY", 6.48),
    501241: ("FIGHT_PROP_ELEMENT_MASTERY", 16.32), 501242: ("FIGHT_PROP_ELEMENT_MASTERY", 18.65),
    501243: ("FIGHT_PROP_ELEMENT_MASTERY", 20.98), 501244: ("FIGHT_PROP_ELEMENT_MASTERY", 23.31),
}


class ArlecchinoMelt:
    """
    Akasha Leaderboard ID: 1000009618
    Team: Arlecchino C0R1, Citlali C0 (TTDS + Cinder City), Xilonen C0R1, Bennett C6 (Aquila + Noblesse)
    """
    calc_id_prefix = "1000009618"

    def __init__(self, base_atk=1016):
        self.base_atk = base_atk
        self.ca_flat_atk_buff = 805.15
        self.na_flat_atk_buff = 2040.53
        self.pyro_resonance_buff = 0.25
        self.setup_dmg_pct = 0.866     # 46.6% Goblet + 40% A4 Passive
        self.static_dmg_pct = 2.0007   # Full rotation DMG% prior to Whimsy stacks
        self.def_mult = 0.487179       # Lv 90 vs Lv 100 Enemy
        self.setup_res_mult = 0.90     # Unshredded 10% Enemy RES during setup E
        self.res_mult = 1.23           # Shreddred RES (10% - 36% Xilonen - 20% Citlali A1)

        self.hit_sequence = [
            {"name": "E_Spike", "mv": 0.26704, "is_melt": False, "is_na": False, "whimsy": 0, "phase": "setup"},
            {"name": "E_Cleave", "mv": 2.40356, "is_melt": False, "is_na": False, "whimsy": 0, "phase": "setup"},
            {"name": "E_Directive", "mv": 0.57227, "is_melt": False, "is_na": False, "whimsy": 0, "phase": "setup"},
            {"name": "CA", "mv": 2.564, "is_melt": True, "is_na": False, "whimsy": 1, "phase": "ca"}
        ]
        whimsy = 2
        for _ in range(5):
            self.hit_sequence.append({"name": "N1", "mv": 0.932, "is_melt": True, "is_na": True, "whimsy": whimsy, "phase": "na"})
            whimsy = min(3, whimsy + 1)
            self.hit_sequence.append({"name": "N2", "mv": 1.022, "is_melt": False, "is_na": True, "whimsy": whimsy, "phase": "na"})
            self.hit_sequence.append({"name": "N3", "mv": 1.282, "is_melt": False, "is_na": True, "whimsy": whimsy, "phase": "na"})

    def calculate_combo(self, stats):
        cr = min(1.0, max(0.0, stats.get("CR", 0.0)))
        cd = stats.get("CD", 0.0)
        em = stats.get("EM", 0.0)
        unbuffed_atk = stats.get("TOTAL_ATK", 0.0) + self.base_atk * self.pyro_resonance_buff

        crit_mult = 1.0 + (cr * cd)
        melt_mult = 2.0 * (1.0 + ((2.78 * em) / (em + 1400.0))) if em > 0 else 2.0

        total_dmg = 0.0
        current_bol = 0.0

        for hit in self.hit_sequence:
            if hit["phase"] == "setup":
                active_atk = unbuffed_atk
                dmg_pct = self.setup_dmg_pct
                res = self.setup_res_mult
            elif hit["phase"] == "ca":
                active_atk = unbuffed_atk + self.ca_flat_atk_buff
                dmg_pct = self.static_dmg_pct + (hit["whimsy"] * 0.18)
                res = self.res_mult
            else:
                active_atk = unbuffed_atk + self.na_flat_atk_buff
                dmg_pct = self.static_dmg_pct + (hit["whimsy"] * 0.18)
                res = self.res_mult

            masque = (current_bol * 2.38) if (hit["is_na"] and current_bol >= 0.30) else 0.0
            base_hit = active_atk * (hit["mv"] + masque)
            hit_dmg = base_hit * (1.0 + dmg_pct) * crit_mult * self.def_mult * res

            if hit["is_melt"]:
                hit_dmg *= melt_mult

            total_dmg += hit_dmg

            if hit["name"] == "CA":
                current_bol = 1.55
            elif hit["is_na"]:
                current_bol *= 0.925

        return total_dmg


# Registry mapping Character ID (or Name) to available rotation classes
ROTATION_REGISTRY = {
    10000096: {
        "name": "Arlecchino",
        "rotations": {
            "Melt Combo (Crimson Moon, Citlali/Xilonen/Bennett)": ArlecchinoMelt
        }
    }
}