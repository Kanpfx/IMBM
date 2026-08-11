"""Constants used by the active Ares bot integration."""

from sc2.ids.unit_typeid import UnitTypeId as UnitID

UNIT_TYPE_TO_NUM_REPAIRERS: dict[UnitID, int] = {
    UnitID.BUNKER: 4,
    UnitID.SUPPLYDEPOT: 3,
    UnitID.BARRACKS: 2,
    UnitID.BARRACKSREACTOR: 2,
    UnitID.FACTORYREACTOR: 2,
    UnitID.BARRACKSTECHLAB: 2,
    UnitID.FACTORYTECHLAB: 2,
    UnitID.COMMANDCENTER: 2,
    UnitID.ORBITALCOMMAND: 2,
    UnitID.PLANETARYFORTRESS: 6,
    UnitID.FACTORY: 2,
    UnitID.STARPORT: 2,
    UnitID.BATTLECRUISER: 3,
    UnitID.CYCLONE: 2,
    UnitID.RAVEN: 2,
    UnitID.HELLION: 2,
    UnitID.MEDIVAC: 2,
    UnitID.SIEGETANK: 3,
    UnitID.SIEGETANKSIEGED: 3,
    UnitID.VIKINGFIGHTER: 3,
    UnitID.WIDOWMINEBURROWED: 1,
}
