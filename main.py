# main.py
import itertools
from collections import defaultdict
import requests
from rotations import (
    STAT_MAX, TIERS, ENKA_PROP_MAP, PROP_DISPLAY_NAME,
    SUBSTAT_ROLL_IDS, ROTATION_REGISTRY
)

DEFAULT_UID = "724420955"
HEADERS = {"User-Agent": "GenshinArtifactRerollCLI/2.0"}

EQUIP_SLOTS = {
    "1": ("EQUIP_BRACER", "Flower of Life"),
    "2": ("EQUIP_NECKLACE", "Plume of Death"),
    "3": ("EQUIP_SHOES", "Sands of Eon"),
    "4": ("EQUIP_RING", "Goblet of Eonothem"),
    "5": ("EQUIP_DRESS", "Circlet of Logos"),
}

# Precompute exact probability distribution of tier multiplier sums for k in 0..5 rolls
TIER_SUM_DIST = {}
for k in range(6):
    dist = defaultdict(float)
    prob = (1.0 / len(TIERS)) ** k
    for combo in itertools.product(TIERS, repeat=k):
        dist[round(sum(combo), 4)] += prob
    TIER_SUM_DIST[k] = list(dist.items())


def generate_pity_multisets(total_rolls, guaranteed_rolls):
    """
    Traverses HoYoverse's conditional pity tree for 4 substat slots:
    Slots 0 and 1 = Locked Substats
    Slots 2 and 3 = Unlocked Substats
    Returns a dict mapping (c0, c1, c2, c3) roll counts to their exact probability.
    """
    max_misses = max(0, total_rolls - guaranteed_rolls)
    multisets = defaultdict(float)

    def traverse(counts, prob, rolls_left, misses):
        if rolls_left == 0:
            multisets[tuple(counts)] += prob
            return

        if misses >= max_misses:
            # Pity active: 50% chance each for locked slot 0 or 1
            for slot in (0, 1):
                nxt = list(counts)
                nxt[slot] += 1
                traverse(nxt, prob * 0.5, rolls_left - 1, misses)
        else:
            # Normal roll: 25% chance across all 4 slots
            for slot in range(4):
                nxt = list(counts)
                nxt[slot] += 1
                new_misses = misses + (1 if slot in (2, 3) else 0)
                traverse(nxt, prob * 0.25, rolls_left - 1, new_misses)

    traverse([0, 0, 0, 0], 1.0, total_rolls, 0)
    return multisets


def evaluate_guarantee_tier(sim_model, base_no_art, new_art_base, slot_stat_keys, total_rolls, guaranteed_rolls, sim_baseline):
    """
    Evaluates Win Rate, Worst, Expected Avg, and Best % delta for a given guarantee tier.
    """
    multisets = generate_pity_multisets(total_rolls, guaranteed_rolls)

    expected_delta = 0.0
    win_prob = 0.0
    worst_delta = float("inf")
    best_delta = float("-inf")

    # Collapse dead slots to a single (0.0, 1.0) state to avoid redundant branching
    slot_dists = []
    for s_key in slot_stat_keys:
        if s_key == "DEAD":
            slot_dists.append([(0.0, 1.0)])
        else:
            slot_dists.append(None)

    for counts, m_prob in multisets.items():
        active_Search = [
            [(0.0, 1.0)] if slot_stat_keys[i] == "DEAD" else TIER_SUM_DIST[counts[i]]
            for i in range(4)
        ]

        for (t0, p0), (t1, p1), (t2, p2), (t3, p3) in itertools.product(*active_Search):
            total_prob = m_prob * p0 * p1 * p2 * p3
            tier_sums = (t0, t1, t2, t3)

            sim_gains = {k: 0.0 for k in STAT_MAX}
            for idx, s_key in enumerate(slot_stat_keys):
                sim_gains[s_key] += STAT_MAX[s_key] * tier_sums[idx]

            sim_stats = {
                "CR": base_no_art["CR"] + new_art_base["CR"] + sim_gains["CR"],
                "CD": base_no_art["CD"] + new_art_base["CD"] + sim_gains["CD"],
                "EM": base_no_art["EM"] + new_art_base["EM"] + sim_gains["EM"],
                "TOTAL_ATK": (
                    base_no_art["TOTAL_ATK"]
                    + (sim_model.base_atk * new_art_base["ATK_PCT"]) + new_art_base["FLAT_ATK"]
                    + (sim_model.base_atk * sim_gains["ATK_PCT"]) + sim_gains["FLAT_ATK"]
                )
            }

            dmg = sim_model.calculate_combo(sim_stats)
            delta = (dmg / sim_baseline) - 1.0

            expected_delta += delta * total_prob
            if delta > 1e-9:
                win_prob += total_prob
            if delta < worst_delta:
                worst_delta = delta
            if delta > best_delta:
                best_delta = delta

    return win_prob * 100.0, worst_delta * 100.0, expected_delta * 100.0, best_delta * 100.0


def parse_enka_artifact(equip_item):
    """
    Extracts total current stats, +0 base stats (first 4 roll IDs),
    substat slot order, and total upgrades (4 or 5) directly from Enka's payload.
    """
    rel = equip_item.get("reliquary", {})
    flat = equip_item.get("flat", {})
    roll_ids = rel.get("appendPropIdList", [])

    # Total upgrades is total roll IDs minus the 4 starting substats
    total_upgrades = max(4, min(5, len(roll_ids) - 4)) if roll_ids else 5

    # 1. Current total substats on the equipped +20 piece
    equipped_totals = {k: 0.0 for k in STAT_MAX}
    substat_slots = []  # List of dicts: {"prop_id": str, "stat_key": str, "label": str, "current_val": float, "base_val": float}

    for sub in flat.get("reliquarySubstats", []):
        prop_id = sub.get("appendPropId")
        val = float(sub.get("statValue", 0.0))
        stat_key, is_pct = ENKA_PROP_MAP.get(prop_id, ("DEAD", False))
        scaled_val = (val / 100.0) if is_pct else val
        equipped_totals[stat_key] += scaled_val

        substat_slots.append({
            "prop_id": prop_id,
            "stat_key": stat_key,
            "label": PROP_DISPLAY_NAME.get(prop_id, prop_id),
            "is_pct": is_pct,
            "current_raw": val,
            "base_raw": 0.0,
            "base_scaled": 0.0
        })

    # 2. Reconstruct exact +0/+4 base substats from the first 4 roll IDs
    new_art_base = {k: 0.0 for k in STAT_MAX}
    if len(roll_ids) >= 4 and all(rid in SUBSTAT_ROLL_IDS for rid in roll_ids[:4]):
        for rid in roll_ids[:4]:
            prop_id, raw_val = SUBSTAT_ROLL_IDS[rid]
            stat_key, is_pct = ENKA_PROP_MAP.get(prop_id, ("DEAD", False))
            scaled_val = (raw_val / 100.0) if is_pct else raw_val
            new_art_base[stat_key] += scaled_val
            for slot in substat_slots:
                if slot["prop_id"] == prop_id:
                    slot["base_raw"] = raw_val
                    slot["base_scaled"] = scaled_val
    else:
        # Fallback if roll IDs are unavailable: assume 85% median base roll
        for slot in substat_slots:
            s_key = slot["stat_key"]
            new_art_base[s_key] += STAT_MAX[s_key] * 0.85

    return equipped_totals, new_art_base, substat_slots, total_upgrades


def fetch_akasha_baseline(uid, char_id, calc_id_prefix):
    """Fetches the live leaderboard damage result from Akasha's API."""
    try:
        url = f"https://akasha.cv/api/getCalculationsForUser/{uid}"
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        for build in res.get("data", []):
            if build.get("characterId") == char_id:
                md5 = build.get("md5")
                fit = build.get("calculations", {}).get("fit", {})
                if str(fit.get("calculationId", "")).startswith(calc_id_prefix):
                    return fit.get("result"), md5
                # If 'fit' is a different leaderboard, query damageDistribution directly
                if md5:
                    dist_url = f"https://akasha.cv/api/damageDistribution/{calc_id_prefix}/{uid}/{md5}"
                    dist_res = requests.get(dist_url, headers=HEADERS, timeout=10).json()
                    for item in dist_res.get("data", []):
                        if str(item.get("id")) == calc_id_prefix:
                            return item.get("result"), md5
    except Exception as exc:
        print(f"[!] Warning: Could not reach Akasha API ({exc}). Using local baseline.")
    return None, None


def main():
    # Step 1: Ask for UID (Default 724420955)
    uid = input(f"1. Enter Genshin UID [default: {DEFAULT_UID}]: ").strip() or DEFAULT_UID

    print(f"\n[+] Querying Enka.Network showcase for UID {uid}...")
    enka_url = f"https://enka.network/api/uid/{uid}"
    resp = requests.get(enka_url, headers=HEADERS, timeout=10)
    if resp.status_code != 200:
        print(f"[-] Enka API Error (HTTP {resp.status_code}). Ensure showcase is public.")
        return

    enka_data = resp.json()
    avatars = enka_data.get("avatarInfoList", [])[:12]
    if not avatars:
        print("[-] No characters found in Enka showcase.")
        return

    # Cross-reference names from Akasha or fallback to ROTATION_REGISTRY
    akasha_names = {}
    try:
        ak_res = requests.get(f"https://akasha.cv/api/getCalculationsForUser/{uid}", headers=HEADERS, timeout=8).json()
        for b in ak_res.get("data", []):
            akasha_names[b.get("characterId")] = b.get("name")
    except Exception:
        pass

    # Step 2: Ask for Showcase Character (max 12)
    print("\n--- Showcased Characters (Max 12) ---")
    for idx, av in enumerate(avatars):
        cid = av.get("avatarId")
        cname = akasha_names.get(cid) or ROTATION_REGISTRY.get(cid, {}).get("name") or f"Avatar ID {cid}"
        supported = " [Supported]" if cid in ROTATION_REGISTRY else ""
        print(f"  [{idx + 1}] {cname}{supported}")

    c_idx = int(input("\n2. Select character number: ").strip()) - 1
    chosen_avatar = avatars[c_idx]
    char_id = chosen_avatar.get("avatarId")

    if char_id not in ROTATION_REGISTRY:
        print(f"[-] Character ID {char_id} does not have a rotation configured in rotations.py yet.")
        return

    char_entry = ROTATION_REGISTRY[char_id]
    char_name = char_entry["name"]

    # Extract character's standing stats from Enka fightPropMap
    f_props = chosen_avatar.get("fightPropMap", {})
    base_atk = float(f_props.get("4", 1016.0))
    char_stats = {
        "TOTAL_ATK": float(f_props.get("2001", 2070.0)),
        "CR": float(f_props.get("20", 0.831)),
        "CD": float(f_props.get("22", 2.244)),
        "EM": float(f_props.get("28", 296.0)),
    }

    # Step 3: Ask for Rotation & Artifact Slot
    rot_names = list(char_entry["rotations"].keys())
    print(f"\n--- Available Rotations for {char_name} ---")
    for idx, r_name in enumerate(rot_names):
        print(f"  [{idx + 1}] {r_name}")
    r_idx = int(input("\n3a. Select rotation number [default: 1]: ").strip() or "1") - 1
    rot_cls = char_entry["rotations"][rot_names[r_idx]]
    sim_model = rot_cls(base_atk=base_atk)

    print("\n--- Equipped Artifacts ---")
    equip_by_type = {
        item.get("flat", {}).get("equipType"): item
        for item in chosen_avatar.get("equipList", [])
        if "reliquary" in item
    }
    for k, (eq_type, slot_label) in EQUIP_SLOTS.items():
        piece = equip_by_type.get(eq_type)
        if piece:
            subs_str = ", ".join(
                f"{PROP_DISPLAY_NAME.get(s['appendPropId'], s['appendPropId'])}: {s['statValue']}"
                for s in piece["flat"].get("reliquarySubstats", [])
            )
            print(f"  [{k}] {slot_label:<20} | {subs_str}")

    s_choice = input("\n3b. Select artifact slot to reroll (1-5): ").strip()
    eq_type, slot_label = EQUIP_SLOTS[s_choice]
    target_piece = equip_by_type[eq_type]

    eq_totals, new_art_base, substat_slots, total_upgrades = parse_enka_artifact(target_piece)

    # Step 4: Ask which 2 substats to lock
    print(f"\n--- Substats on {slot_label} ({total_upgrades}-Roll Piece) ---")
    for idx, s in enumerate(substat_slots):
        pct_char = "%" if s["is_pct"] else ""
        print(f"  [{idx + 1}] {s['label']:<18} (Current: +{s['current_raw']}{pct_char} | Base +0: +{s['base_raw']:.2f}{pct_char})")

    lock_input = input("\n4. Enter the 2 substat numbers to LOCK (e.g., 1,2): ").strip()
    lock_indices = [int(x.strip()) - 1 for x in lock_input.replace(" ", ",").split(",") if x.strip()][:2]
    unlocked_indices = [i for i in range(4) if i not in lock_indices]

    # Order the 4 slots so indices 0, 1 are Locked and 2, 3 are Unlocked
    ordered_slots = [substat_slots[i] for i in lock_indices + unlocked_indices]
    slot_stat_keys = [s["stat_key"] for s in ordered_slots]
    locked_labels = [substat_slots[i]["label"] for i in lock_indices]

    # Strip equipped artifact from standing stats
    base_no_art = {
        "CR": char_stats["CR"] - eq_totals["CR"],
        "CD": char_stats["CD"] - eq_totals["CD"],
        "EM": char_stats["EM"] - eq_totals["EM"],
        "TOTAL_ATK": char_stats["TOTAL_ATK"] - (base_atk * eq_totals["ATK_PCT"]) - eq_totals["FLAT_ATK"],
    }

    sim_baseline = sim_model.calculate_combo(char_stats)
    akasha_dmg, md5_hash = fetch_akasha_baseline(uid, char_id, sim_model.calc_id_prefix)
    reference_dmg = akasha_dmg if akasha_dmg else sim_baseline
    
    # --- DEBUG DIAGNOSTIC BLOCK ---
    print("\n[DEBUG] Stat Breakdown Check:")
    print(f"  Enka Standing ATK   : {char_stats['TOTAL_ATK']}")
    print(f"  Stripped Base ATK   : {base_no_art['TOTAL_ATK']}")
    print(f"  Enka Standing CR    : {char_stats['CR']*100:.2f}% (Stripped: {base_no_art['CR']*100:.2f}%)")
    print(f"  Enka Standing CD    : {char_stats['CD']*100:.2f}% (Stripped: {base_no_art['CD']*100:.2f}%)")
    print(f"  Enka Standing EM    : {char_stats['EM']} (Stripped: {base_no_art['EM']})")
    print(f"  Local Sim Baseline  : {sim_baseline:,.0f}")
    print(f"  Akasha Target DMG   : {reference_dmg:,.0f}")
    print(f"  Ratio (Akasha/Local): {reference_dmg / sim_baseline:.16f}")
    print("-" * 50)

    # Step 5: Print Formatted CLI Table for 2, 3, and 4 Guaranteed Rolls
    print("\n" + "=" * 86)
    print(f" ARTIFACT REROLL SIMULATION: {char_name.upper()} - {slot_label.upper()}")
    print("-" * 86)
    print(f" Active Build MD5   : {md5_hash or 'Local Enka Snapshot'}")
    print(f" Akasha Combo DMG   : {reference_dmg:,.0f} (Local Sim: {sim_baseline:,.0f})")
    print(f" Total Upgrades     : {total_upgrades} Rolls ({'4-Liner' if total_upgrades == 5 else '3-Liner'})")
    print(f" Locked Substats    : {locked_labels[0]} & {locked_labels[1]}")
    print("=" * 86)
    print(f" {'Guarantee Tier':<16} | {'Win Rate':>10} | {'Worst Case':>12} | {'Expected Avg':>13} | {'Best Case':>11} | {'Expected DMG':>14}")
    print("-" * 86)

    for guaranteed in (2, 3, 4):
        win_p, worst_d, exp_d, best_d = evaluate_guarantee_tier(
            sim_model=sim_model,
            base_no_art=base_no_art,
            new_art_base=new_art_base,
            slot_stat_keys=slot_stat_keys,
            total_rolls=total_upgrades,
            guaranteed_rolls=guaranteed,
            sim_baseline=sim_baseline,
        )
        proj_dmg = reference_dmg * (1.0 + (exp_d / 100.0))
        print(
            f" {guaranteed} Guaranteed     | {win_p:>9.2f}% | {worst_d:>+11.2f}% | "
            f"{exp_d:>+12.2f}% | {best_d:>+10.2f}% | {proj_dmg:>14,.0f}"
        )

    print("=" * 86 + "\n")


if __name__ == "__main__":
    main()