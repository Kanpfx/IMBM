from sc2.ids.unit_typeid import UnitTypeId


class EconomyMixin:
    async def distribute_workers(self, resource_ratio: float = 2.0) -> None:
        if not self.townhalls.ready or not self.workers:
            return

        mineral_patches = {
            mineral
            for townhall in self.townhalls.ready
            for mineral in self.mineral_field.closer_than(12, townhall)
        }
        gas_refineries = {
            gas
            for townhall in self.townhalls.ready
            for gas in self.gas_buildings.ready.closer_than(12, townhall)
            if gas.has_vespene
        }

        if self.config.own_race == "Terran":
            await self._deploy_mules(mineral_patches)

        available_idle_workers = list(self.workers.idle)

        for gas_site in gas_refineries:
            if gas_site.surplus_harvesters > 0:
                gas_workers = [
                    worker
                    for worker in self.workers.gathering
                    if worker.distance_to(gas_site) < 2
                ]
                for worker in gas_workers[: gas_site.surplus_harvesters]:
                    available_idle_workers.append(worker)

        gas_tasks = {
            gas: max(0, -gas.surplus_harvesters)
            for gas in gas_refineries
            if max(0, -gas.surplus_harvesters)
        }
        mineral_tasks = {}
        for mineral in mineral_patches:
            worker_count = 0
            for worker in self.workers.gathering:
                if worker.distance_to(mineral) < 2 and worker not in available_idle_workers:
                    worker_count += 1
            need = max(0, 2 - worker_count)
            if need:
                mineral_tasks[mineral] = need

        for gas_site in list(gas_tasks.keys()):
            needed = gas_tasks[gas_site]
            nearby_mineral_workers = []
            for mineral in mineral_patches:
                if mineral.distance_to(gas_site) < 10:
                    for worker in self.workers.gathering:
                        if worker.distance_to(mineral) < 2 and worker not in available_idle_workers:
                            nearby_mineral_workers.append((worker, worker.distance_to(gas_site)))

            nearby_mineral_workers.sort(key=lambda item: item[1])
            for worker, _ in nearby_mineral_workers[:needed]:
                worker.gather(gas_site)
                needed -= 1

            if needed > 0 and available_idle_workers:
                available_idle_workers.sort(key=lambda worker: worker.distance_to(gas_site))
                assigned = available_idle_workers[:needed]
                for worker in assigned:
                    worker.gather(gas_site)
                available_idle_workers = available_idle_workers[len(assigned):]
                needed -= len(assigned)

            if needed <= 0:
                del gas_tasks[gas_site]
            else:
                gas_tasks[gas_site] = needed

        for worker in available_idle_workers:
            if not mineral_tasks:
                break
            target = min(mineral_tasks.keys(), key=lambda mineral: mineral.distance_to(worker))
            worker.gather(target)
            mineral_tasks[target] -= 1
            if mineral_tasks[target] <= 0:
                del mineral_tasks[target]

        for gas_site in list(gas_tasks.keys()):
            needed = gas_tasks[gas_site]
            if needed <= 0:
                continue

            distant_mineral_workers = []
            for mineral in mineral_patches:
                if mineral.distance_to(gas_site) < 15:
                    for worker in self.workers.gathering:
                        if worker.distance_to(mineral) < 2 and worker not in available_idle_workers:
                            distant_mineral_workers.append((worker, worker.distance_to(gas_site)))

            distant_mineral_workers.sort(key=lambda item: item[1])
            reassigned = 0
            for worker, _ in distant_mineral_workers:
                if reassigned >= needed:
                    break
                worker.gather(gas_site)
                reassigned += 1

    async def _deploy_mules(self, mineral_patches) -> None:
        mule_units = self.units(UnitTypeId.MULE).idle
        for mule in mule_units:
            nearby_minerals = [mineral for mineral in mineral_patches if mineral.distance_to(mule) < 12]
            best_mineral = self._select_best_mineral_for_mule(nearby_minerals, mule)
            if best_mineral:
                mule.gather(best_mineral)

    def _select_best_mineral_for_mule(self, mineral_patches, orbital_command):
        if not mineral_patches:
            return None

        best_mineral = None
        best_score = -1
        for mineral in mineral_patches:
            score = 0
            score += (mineral.mineral_contents / 1800) * 40
            score += (1 - (mineral.distance_to(orbital_command) / 12)) * 20

            current_harvesters = 0
            for unit in self.units:
                if (
                    hasattr(unit, "order_target")
                    and unit.order_target == mineral.tag
                    and unit.type_id in [UnitTypeId.SCV, UnitTypeId.MULE]
                ):
                    current_harvesters += 1
            score += max(0, 1 - current_harvesters / 4) * 30

            mule_count = 0
            for unit in self.units.filter(lambda candidate: candidate.type_id == UnitTypeId.MULE):
                if hasattr(unit, "order_target") and unit.order_target == mineral.tag:
                    mule_count += 1
            if mule_count >= 1:
                score -= 50
            if mineral.mineral_contents < 500:
                score -= 20

            if score > best_score:
                best_score = score
                best_mineral = mineral

        return best_mineral if best_score > 0 else None
