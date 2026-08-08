Made with [ares-sc2 framework](https://github.com/AresSC2/ares-sc2)  
[Bot repo](https://github.com/raspersc2/why)

---
# why?
Terran has access to a variety of sharp, sometimes gimmicky strategies that tend to appear and disappear on 
ladder. This bot is meant as a test opponent that uses those kinds of builds, 
so bots can practice against them. The bot is open source and designed to work with the 
[local play bootstrap docker image](https://github.com/aiarena/local-play-bootstrap).

Suggestions for improving or expanding the builds are always welcome.

Please don’t reupload this bot directly to the ladder. You’re more than welcome, though, 
to use it as a resource or inspiration when creating your own bot.

## builds

The following builds are available (with the possibility of more later):
- ProxyReaperWithPf
- MassMine
- ProxyMarauder
- Reapers
- ProxyMarine
- MightBeAWorkerRush
- BattleCruiserRush
- ThorDrop
- WorkerRush

## testing
This bot can be downloaded and used for testing via the [local play bootstrap docker image](https://github.com/aiarena/local-play-bootstrap).

The `terran_builds.yml` file can be edited to test against specific builds.

## IMBM run

The runtime is now LLM/IMBM-only; the original openings are not executed. Set
`LLM_IMBM_MODEL`, `LLM_IMBM_BASE_URL`, and `LLM_IMBM_API_KEY`, then run:

```powershell
conda run -n StarWM python run.py --map_name Flat64 --difficulty Hard --ai_build Macro --enemy_race Terran --enable_bm
```

`--bm` and `-bm` are aliases for `--enable_bm`. With BM enabled, the first BM
response is awaited before IM starts; later BM updates run asynchronously every
240 python-sc2 iterations. Without the flag, IM runs with no BM guidance.

Use `python run.py --help` for the complete explicit map/opponent/BM options.
