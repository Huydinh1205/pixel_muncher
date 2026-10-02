# Testing on a laptop (macOS or Linux)

You can test the app on a laptop without the GPU workstation. There are two modes:

| Command | Imagery | Tiling | Classification |
|---|---|---|---|
| `bash run.sh --mock` | built-in fake data | fake | fake |
| `bash run.sh --local` | your own `.tif` files | real, GDAL `gdal2tiles` | fake, coloured by greenness |

Real Pixel Muncher needs an NVIDIA GPU with CUDA, so it only runs on the
workstation. In both laptop modes, `mock/fake_inference.py` takes its place.
In `--local` mode it reads each real tile and colours pixels by the Excess
Green index ((2G - R - B) / (R + G + B)). That colouring is not a model. It
lets you check the parts of the workflow that do not need a GPU on real
imagery: tiling, the job queue, how results are organised, the run manifest
and the map.

Windows is not supported (the job runner uses POSIX process groups). Use WSL.

## 1. Open a terminal in the project folder

```bash
cd ~/path/to/pixel-muncher-gui
```

## 2. Check that conda is installed

```bash
conda --version
```

If the command is not found, install Miniforge, a small conda distribution
that uses conda-forge by default:

```bash
brew install miniforge        # macOS with Homebrew
conda init zsh                # or: conda init bash
```

Close the terminal, open a new one and go back to step 1.

## 3. Create an environment with GDAL (once)

GDAL installs cleanly from conda-forge. Installing it with pip on macOS often
fails, because pip has to compile it against the GDAL C library.

```bash
conda create -n pxm -c conda-forge python=3.11 gdal pillow numpy -y
conda activate pxm
pip install -r requirements.txt
```

Check GDAL:

```bash
python -c "from osgeo_utils import gdal2tiles; from osgeo import gdal; print('GDAL', gdal.__version__)"
```

It should print `GDAL 3.x.x`. Run `conda activate pxm` in every new terminal
before you start the app.

## 4. Try the demo first

```bash
bash run.sh --mock
```

Open http://127.0.0.1:8080 and choose `SiteA`. Press **Add to queue** and
watch the *Runs* tab. Stop the app with `Ctrl+C`.

## 5. Test with your own orthomosaic

Every orthomosaic must sit in its own project folder inside `local_data/`. The
folder name becomes the project name.

```bash
mkdir -p local_data/TestSite
```

For a small orthomosaic (under about 1 GB), link to it instead of copying it:

```bash
ln -s "/path/to/ortho.tif" local_data/TestSite/
```

A large orthomosaic can produce tens of thousands of tiles at zoom 23. To keep
the test short, cut a 5000 × 5000 pixel piece from the middle first:

```bash
gdalinfo "/path/to/ortho.tif" | grep "Size is"
# e.g. "Size is 40000, 30000" -> take the centre:
gdal_translate -srcwin 17500 12500 5000 5000 -co COMPRESS=DEFLATE \
  "/path/to/ortho.tif" local_data/TestSite/TestSite_crop.tif
```

Start the app in local mode:

```bash
bash run.sh --local
```

At http://127.0.0.1:8080:

1. Choose `TestSite / ...tif`. *Make tiles* switches on by itself, because no tiles exist yet.
2. Choose a model. In local mode the model files are placeholders.
3. Optionally turn on the confidence slider. At 0.95, more pixels stay unclassified.
4. Press **Add to queue** and open the *Runs* tab to follow the log and progress.
5. When the job is done, press **Open map**. The classification is drawn over
   the orthomosaic. Use the slider to change its opacity. The map works offline.

Results are written to
`local_data/TestSite_Result/<date>_<model>_<confidence>/`. The folder holds the
classified tiles in `23/`, plus `log.log`, `run_manifest.json` and `model_config/`.

## 6. Things worth trying

- Run the same file again with *Make tiles* off. The job skips tiling and finishes sooner.
- Queue two jobs back to back. The second waits until the first is done.
- Press *Cancel* while a job is running.
- Start with `MOCK_FAIL=1 bash run.sh --local`. The job then fails halfway, so
  you can see how the app reports errors.
- Stop the app with `Ctrl+C` while a job runs, then start it again. The job is
  marked *Failed (Interrupted)*.

## 7. Make a Mac app icon

Build `Pixel Muncher.app` once, then start the app from Finder, Launchpad or
the Dock instead of the terminal:

```bash
bash launchers/macos/make_app.sh            # opens your .tif files (--local mode)
bash launchers/macos/make_app.sh --mock     # or: demo mode
```

The app appears in the project folder. Double-click it. If the server is not
running, it starts it with the `pxm` conda environment and opens Pixel
Muncher in its own window (Chrome, Edge or Brave in app mode, otherwise
Safari). To keep it in the Dock, drag `Pixel Muncher.app` from Finder onto the Dock.

In laptop modes, the power button at the top right of the window stops the
server. Closing the window leaves the server running in the background.

Keep the `.app` inside the project folder. If you move the folder, run
`make_app.sh` again. When the app cannot start, the reason is in
`local_state/app.log`.

## Common problems

| Problem | Fix |
|---|---|
| `Tiling tool: ... cannot import osgeo_utils.gdal2tiles` | Run `conda activate pxm` before `bash run.sh --local` |
| `Address already in use` | Port 8080 is taken. Change `port:` in `config.local.yaml` |
| Your `.tif` is not listed | It must be in `local_data/<Project>/`, not directly in `local_data/`. Press the refresh button |
| The map is empty | The orthomosaic may have no coordinate system. Check with `gdalinfo file.tif` |
| The Mac app says no Python environment was found | Create the `pxm` environment (step 3). If conda is in an unusual place, start it once from a terminal with `PXM_GUI_PYTHON=/path/to/python bash run.sh --local` |
| macOS blocks the app the first time | Right-click the app, choose *Open*, then *Open* again |

## Running the tests

```bash
pip install pytest
python -m pytest -q
```
