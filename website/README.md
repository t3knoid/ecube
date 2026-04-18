# ECUBE Marketing Site

This folder contains the public static website source for the ECUBE marketing site.

## Local preview

From the repository root:

```bash
cd website
python3 -m http.server 8080
```

Then open http://localhost:8080.

## Deployment

The GitHub Actions workflow in `.github/workflows/deploy-marketing-site.yml` publishes this site to GitHub Pages for the `www.ecube.one` domain.

The deploy job bundles the static HTML and CSS from this folder and includes staged product screenshots from the frontend snapshot assets.
