# Install Notes

## Initial Setup

Followed the server README recommendation:

```bash
conda create -n multiuav-server python=3.11
conda activate multiuav-server
cd /Users/pearl/Documents/MultiUAV-Plat/server
python -m pip install -r requirements.txt
```

## Issues Encountered

### Python 3.14 + Pygame

Using a Python 3.14 `.venv` caused `pygame==2.5.2` to build from source on macOS and fail due to missing native build tools such as `pkg-config`.

Resolution: use the README's conda environment with Python 3.11.

### Missing Shapely

When running:

```bash
python main.py
```

the server reported:

```text
ModuleNotFoundError: No module named 'shapely'
```

The server imports Shapely in geometry/collision modules, so install it in the active environment:

```bash
conda install -c conda-forge shapely
```

or:

```bash
python -m pip install shapely
```

## Current Status

- Server:
- UI/controller:
- Example sessions imported:
- First task run:
