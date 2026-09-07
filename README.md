# basarorsel.com

Başar Örsel's portfolio: training data, projects and code. Sibling of [basarorsel.me](https://basarorsel.me); business lives at [orselstudio.tech](https://orselstudio.tech).

## Runtime

`index.html` is the deployable artifact. Open it directly or serve it with any static HTTP server. CSS, JavaScript, brand SVGs and the training JSON are embedded. No runtime dependency, build toolchain, account, tracking or network call is needed for the charts. External links are ordinary navigation.

The original identity site's CSS is preserved verbatim, with portfolio/dashboard rules appended. The hash router exposes Home, Sports, Data, Projects, Code and Directory. AUTO follows the visitor's local hour (light 07:00–18:59, dark otherwise); LIGHT/DARK overrides persist in localStorage. This is a clock-based approximation, not an astronomical sunrise calculation.

## Reproduce the page

Python's standard library is enough to render the committed snapshot:

```sh
python3 build_site.py
python3 -m unittest -v
python3 -m http.server 8768 --bind 127.0.0.1
```

To recompute from your own HealthFit FIT exports, install `fitdecode` in a local virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python build_site.py --fit-dir /path/to/fit/exports
```

This updates `data.json` and `index.html`. Raw FIT files are not part of this repository. `fit_pipeline.py` is the actual parser and aggregator from the original training-dashboard project, not a mock. Unreadable files stop the build rather than being silently skipped. Duplicate start-time/sport sessions are removed. Monthly/weekly distance sums are asserted against the total, within rounding tolerance.

## Data and limits

Every displayed training statistic comes from `const D` embedded in the page. Explicit Sports targets (E21E 2027, 3000 m under 10:00) are goals, not computed results. Current detraining is self-reported; historical bests are not current fitness estimates.

The dashboard contains monthly and weekly volume, quarterly pace/HR means, per-run scatter, Banister TRIMP load curves, decoupling, route-density drawings, long-run elevation profiles and record tables. Chart filtering and physiological assumptions are documented beside the charts and in the expandable Methods section. GPS rolling splits are not certified race results. Resting HR is assumed; the highest logged HR is not necessarily physiological HRmax. Missing logs do not establish inactivity. Raw route traces are reduced to projected SVG paths; they remain potentially identifying.

The aggregate contains dates, heart-rate summaries and route shapes and is deliberately public. Do not put raw watch files, credentials or unrelated health data in this repo.

## Deployment

GitHub Pages: `main`, repository root. `.nojekyll` disables Jekyll processing; no workflow or package installation is required to serve the committed page. `CNAME` declares `basarorsel.com`. DNS is managed separately, not by this repository. The GitHub Pages project URL may redirect to the custom domain once CNAME is configured; DNS/TLS must be ready before that domain can be considered live.
