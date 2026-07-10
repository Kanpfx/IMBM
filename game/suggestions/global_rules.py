def get_global_suggestions(player):
    suggestions = []

    if player.enemy_units.exists:
        n_enemies = len(
            [unit for unit in player.enemy_units if unit.name not in ["Probe", "SCV", "Drone", "MULE", "Overlord"]]
        )
        if n_enemies > 0:
            suggestions.append(
                f"Enemy units detected ({n_enemies} units), consider attacking them."
            )

    if player.time < 300 and player.time > 60:
        suggestions.append("The enemy will start a fierce attack at 03:00, so you need to start producing a large number of attack units, such as Marauder, at least at 02:30.")

    if player.time > 300 and player.supply_army > 15 and len(player.enemy_units) < 8:
        suggestions.append("We can win the game right away! Please find and eliminate all enemies as soon as possible.")

    if player.minerals >= 500:
        suggestions.append("Too much minerals! Consider spending them on expanding or developing high technology.")

    return suggestions

