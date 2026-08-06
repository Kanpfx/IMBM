# Dependencies

## Ares

The project uses [Ares](https://github.com/AresSC2/ares-sc2) as a Git
submodule at tag `v3.9.6` (`0ac34b87f9471979f8de19a77020eed2d8693b26`).
The checked-out commit recorded by the parent repository is the authoritative
pin. `pyproject.toml` installs it through the local `ares-sc2` path.

Clone with submodules:

```bash
git clone --recurse-submodules <repository-url>
```

For an existing clone:

```bash
git submodule update --init --recursive
```

To upgrade Ares, checkout a deliberately selected upstream tag or commit in
`ares-sc2`, update `poetry.lock` if required, test the project, then commit the
submodule pointer and the lock file together.
