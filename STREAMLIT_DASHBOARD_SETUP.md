# Streamlit Flood-Risk Dashboard

This dashboard calls the authenticated Django backend and the model proxy endpoints under `/api/model/`.

## Configure

Set the backend base URL without a trailing path. Use either Streamlit secrets:

```toml
API_BASE_URL = "https://your-django-backend.example.com"
```

or an environment variable:

```bash
API_BASE_URL="https://your-django-backend.example.com"
```

The app logs in through `POST /auth/login/` and stores only the returned access token in `st.session_state`.

The interpretation service uses the separate setting `INTERPRETATION_API_BASE_URL`; it can be set in Streamlit secrets or as an environment variable. If omitted, the frontend uses the interpretation-service URL supplied for this integration:

```toml
INTERPRETATION_API_BASE_URL = "https://9520-102-206-113-162.ngrok-free.app"
```

```powershell
$env:INTERPRETATION_API_BASE_URL = "https://your-current-interpretation-tunnel.ngrok-free.app"
```

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## API Notes

The frontend uses:

- `GET /api/model/health/`
- `GET /api/model/buildings/`
- `GET /api/model/portfolio-summary/`
- `GET /api/model/metrics/`
- `GET /api/model/formula/`
- `GET /api/model/quote/<building_id>/`
- `POST /api/model/quote/`

The UI renders charts and filters only when the backend response includes the fields needed for them.

The overview and location-search charts are grouped from the current `/api/model/buildings/` response and update when a chart measure or neighborhood search changes. Location search looks for fields such as `neighbourhood`, `neighborhood`, `estate`, `area`, `ward`, or `address`; asset quotes use the existing quote endpoints. The return-period curve remains portfolio-wide and uses loss data from `/api/model/portfolio-summary/`.

The shared welcome header keeps the notification bell visible across all dashboard pages. The red dot marks the supplied Landmark Plaza broker placement unread; select **Mark as read** to clear the indicator. This is a frontend-seeded preview, not a live broker/cedant inbox feed. Open the memo and financial-engine review in the notification panel, match the placement to the correct building returned by `/api/model/buildings/`, and select **Generate financial-engine insight**. The dashboard uses the existing quote endpoint and labels comparisons with the broker's current premium as non-like-for-like because the submitted policy excludes flood. If the property cannot be matched, no quote is generated; add or identify the correct model building first. The notification panel also accepts a broker report and submits it to `POST /api/upload/`. It displays only financial and risk values returned by that API, charts the returned `financial_summary.losses_per_return_period`, and shows the backend's readiness issues, assumptions, limitations, and warnings. When no loss curve is returned, the panel may chart extracted hazard inputs separately and clearly labels them as raw inputs, not modelled losses. The analysis can be downloaded as a Markdown report. **Generate AI underwriter briefing** sends the structured financial summary and extracted risk records to the authenticated interpretation summary proxy. A 502 “Interpretation service is unavailable” means the backend proxy cannot reach its configured interpretation provider; start/check that service and its upstream URL, then retry. A missing or blocked model run is explicitly reported; the AI explanation does not substitute for a model calculation or underwriting decision.

The **BULK UPLOAD** sidebar page accepts `.txt`, `.md`, `.docx`, `.pdf`, `.xlsx`, `.csv`, `.html`, `.json`, `.py`, `.png`, `.jpg`/`.jpeg`, `.svg`, `.tif`/`.tiff` (GeoTIFF), and `.zip` files. **Upload selected document to backend** sends one selected file per request to `POST /api/upload/` as multipart form data: `file` and `portfolio_name`. The request uses the signed-in bearer token and the configured `API_BASE_URL`. The backend response, including extracted data, model-readiness issues, and warnings, is displayed in the page. Backend upload requires the model/Django API to be reachable. Files are limited to 25 MB each and the selection to 50 MB total. **Generate a local summary** is a separate frontend-only action that produces a downloadable Markdown report with extracted text and structured-data previews; it does not calculate flood risk. ZIP processing is limited to 25 MB of expanded contents. Python files are displayed as source text only and never executed. Raster images/GeoTIFFs are summarized by metadata without OCR; scanned PDFs may not contain extractable text. ZIP archives are inspected in memory, and supported nested files are summarized without writing them to disk.

The separate **API Explorer** page lets signed-in users send read-only `GET` requests to the model health, buildings, portfolio summary, metrics, formula, and per-building quote endpoints. It accepts optional query parameters as a JSON object and displays the returned response or API error. It does not run automatically: choose an endpoint and select **Send GET request**. Bulk Upload and API Explorer do not load the dashboard datasets on page entry, so local file summaries remain usable when the backend is unavailable.

The **EP Curve** follows the reference line-chart layout and uses the backend's portfolio loss-by-return-period data. It sorts valid non-negative losses, draws a smoothed line with markers, and shows the exact number of years, annual chance, and full KES loss on hover. Axis labels adapt to the loss magnitude and the loss table stays sorted by return period. The housing-class loss chart also shows exact values on hover. The **Hotspots** page displays the 24 named locations from `data/nairobi_hotspots_geocoded.csv` on an interactive Nairobi map and in a searchable coordinate table. These are supplied reference locations, not live flood observations. Overview **Explore** buttons navigate to their corresponding pages.

The dashboard **Interpretation** page continues to call the separately configured interpretation service for dashboard summaries and questions. For uploaded documents, after a successful `POST /api/upload/`, select **Generate AI summary** to call the authenticated Django proxy `POST /api/interpretation/summary/` with `portfolio_summary` and `building_risk_summary`. The document chat calls `POST /api/interpretation/question/` with `question` and a `context` containing the uploaded document response and portfolio name. The summary UI displays the returned `summary` and optional `source`; chat displays the returned `answer`. These responses are explanations only, not quotes or underwriting decisions. The local Markdown summary remains a separate option and does not call an AI service.
