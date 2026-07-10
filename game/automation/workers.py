from sc2.ids.unit_typeid import UnitTypeId

from game.automation.mules import deploy_mules


async def distribute_workers(player, resource_ratio: float = 2.0) -> None:
    if not player.townhalls.ready or not player.workers:
        return

    # 只考虑基地附近资源，避免把工人错误拉去远端资源点。
    mineral_patches = {
        m for nexus in player.townhalls.ready
        for m in player.mineral_field.closer_than(12, nexus)
    }
    gas_refineries = {
        g for nexus in player.townhalls.ready
        for g in player.gas_buildings.ready.closer_than(12, nexus)
        if g.has_vespene
    }

    if player.config.own_race == "Terran":
        await deploy_mules(player, mineral_patches)

    available_idle_workers = list(player.workers.idle)

    # 先把气矿过载工人释放出来，后续统一重新分配。
    for gas_site in gas_refineries:
        if gas_site.surplus_harvesters > 0:
            gas_workers = []
            for worker in player.workers.gathering:
                if worker.distance_to(gas_site) < 2:
                    gas_workers.append(worker)

            excess_count = gas_site.surplus_harvesters

            for i in range(min(excess_count, len(gas_workers))):
                worker = gas_workers[i]
                available_idle_workers.append(worker)
                print(f"Marked excess worker from gas for reassignment: {gas_site}")

    gas_tasks = {}
    mineral_tasks = {}

    # gas_tasks/mineral_tasks 表示每个资源点还缺多少工人。
    for g in gas_refineries:
        missing = max(0, -g.surplus_harvesters)
        if missing:
            gas_tasks[g] = missing

    for m in mineral_patches:
        worker_count = 0
        for worker in player.workers.gathering:
            if worker.distance_to(m) < 2 and worker not in available_idle_workers:
                worker_count += 1
        need = max(0, 2 - worker_count)
        if need:
            mineral_tasks[m] = need

    for gas_site in list(gas_tasks.keys()):
        needed = gas_tasks[gas_site]
        if needed <= 0:
            continue

        nearby_mineral_workers = []

        # 优先从附近矿线调工人补气，减少行走损耗。
        for mineral in mineral_patches:
            if mineral.distance_to(gas_site) < 10:
                for worker in player.workers.gathering:
                    if worker.distance_to(mineral) < 2 and worker not in available_idle_workers:
                        nearby_mineral_workers.append((worker, worker.distance_to(gas_site)))

        nearby_mineral_workers.sort(key=lambda x: x[1])

        reassigned = 0
        for worker, _ in nearby_mineral_workers:
            if reassigned >= needed:
                break
            worker.gather(gas_site)
            print(f"Reassigned worker from mineral to gas: {gas_site}")
            reassigned += 1

        needed -= reassigned

        if needed > 0 and available_idle_workers:
            available_idle_workers.sort(key=lambda w: w.distance_to(gas_site))

            assigned = 0
            workers_to_remove = []
            for worker in available_idle_workers:
                if assigned >= needed:
                    break
                worker.gather(gas_site)
                print(f"Assigned idle worker to gas: {gas_site}")
                workers_to_remove.append(worker)
                assigned += 1

            for worker in workers_to_remove:
                available_idle_workers.remove(worker)

            needed -= assigned

        gas_tasks[gas_site] = needed
        if gas_tasks[gas_site] <= 0:
            del gas_tasks[gas_site]

    for worker in available_idle_workers:
        if not mineral_tasks:
            break

        # 闲置工人优先补最近的缺人工矿点。
        target = min(mineral_tasks.keys(), key=lambda s: s.distance_to(worker))
        worker.gather(target)
        print(f"Assigned idle worker to mineral: {target}")

        mineral_tasks[target] -= 1
        if mineral_tasks[target] <= 0:
            del mineral_tasks[target]

    if gas_tasks:
        for gas_site in list(gas_tasks.keys()):
            needed = gas_tasks[gas_site]
            if needed <= 0:
                continue

            distant_mineral_workers = []
            # 近处仍不足时，再扩大搜索范围补气。
            for mineral in mineral_patches:
                if mineral.distance_to(gas_site) < 15:
                    for worker in player.workers.gathering:
                        if worker.distance_to(mineral) < 2 and worker not in available_idle_workers:
                            distant_mineral_workers.append((worker, worker.distance_to(gas_site)))

            distant_mineral_workers.sort(key=lambda x: x[1])

            reassigned = 0
            for worker, _ in distant_mineral_workers:
                if reassigned >= needed:
                    break
                worker.gather(gas_site)
                print(f"Reassigned distant worker from mineral to gas: {gas_site}")
                reassigned += 1
