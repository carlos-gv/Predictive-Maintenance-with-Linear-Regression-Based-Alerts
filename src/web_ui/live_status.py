"""Live Status tab: layout + callbacks for the polling live chart and the debug bulk-load button."""

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate

import db

AXIS_COLUMNS = [f"axis_{i}" for i in range(1, 9)]
# Same validated palette, in the same axis order, as the notebook. Each joint keeps
# one colour across both views so nobody has to re-learn them. These eight were
# checked for colourblind separation; plotly's defaults were not.
AXIS_COLORS = [
    "#2a78d6",  # axis_1 blue
    "#eb6834",  # axis_2 orange
    "#1baf7a",  # axis_3 aqua
    "#eda100",  # axis_4 yellow
    "#e87ba4",  # axis_5 magenta
    "#008300",  # axis_6 green
    "#4a3aa7",  # axis_7 violet
    "#e34948",  # axis_8 red
]

# Poll every 2 seconds, matching the reading interval the workshop specifies.
# Each poll takes the next batch of readings, the way a real dashboard picks up
# whatever has landed since it last looked.
POLL_INTERVAL_MS = 2000
ROLLING_WINDOW_SECONDS = 90

# Whole-shift view is bucketed to this before it reaches the browser. Unaggregated,
# the full table is a 10 MB payload and 317,376 plotted points, which locks the tab.
BULK_BUCKET = "1min"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#d8d7d2"

_BUTTON = {
    "padding": "7px 16px", "marginRight": "8px", "border": f"1px solid {GRID}",
    "borderRadius": "6px", "background": "#ffffff", "color": INK,
    "fontSize": "14px", "cursor": "pointer",
}

layout = html.Div(
    [
        html.Div(
            [
                html.H3("Realtime Current (Amps, stacked)",
                        style={"margin": "0 0 4px 0", "fontSize": "17px", "color": INK}),
                html.Div("Each band is one joint; the top of the stack is total draw.",
                         style={"color": INK_MUTED, "fontSize": "13px", "marginBottom": "14px"}),
            ]
        ),
        html.Div(
            [
                html.Button("Live", id="live-button", n_clicks=0, style=_BUTTON),
                html.Button("Whole shift", id="bulk-load-button", n_clicks=0, style=_BUTTON),
                html.Span(id="bulk-load-status",
                          style={"marginLeft": "6px", "color": INK_MUTED, "fontSize": "13px"}),
            ],
            style={"marginBottom": "10px"},
        ),
        dcc.Graph(id="live-status-chart", config={"displaylogo": False}),
        dcc.Interval(id="poll-interval", interval=POLL_INTERVAL_MS, n_intervals=0),
        dcc.Store(id="buffer-store", data=[]),
        # Which view is on screen. Without this, a poll that fired while the
        # whole-shift query was still running lands afterwards and quietly
        # replaces it with the 90-second live window.
        dcc.Store(id="view-mode", data="live"),
    ],
    style={"maxWidth": "1180px", "margin": "0 auto", "padding": "0 20px 28px"},
)


def _to_records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    out["reading_time"] = out["reading_time"].astype(str)
    return out.to_dict("records")


def _from_records(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["trait", *AXIS_COLUMNS, "reading_time"])
    df = pd.DataFrame(records)
    df["reading_time"] = pd.to_datetime(df["reading_time"], format="ISO8601")
    return df


def _trim_to_window(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = df["reading_time"].max() - pd.Timedelta(seconds=ROLLING_WINDOW_SECONDS)
    return df[df["reading_time"] >= cutoff]


def _build_figure(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if df.empty:
        fig.update_layout(title="Waiting for data...")
        return fig

    for axis, color in zip(AXIS_COLUMNS, AXIS_COLORS):
        fig.add_trace(
            go.Scatter(
                x=df["reading_time"],
                y=df[axis],
                name=axis.replace("_", " ").title(),
                mode="lines",
                stackgroup="axes",
                line=dict(width=0.5, color=color),
            )
        )

    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Current (A)",
        legend_title="Axis",
        margin=dict(l=52, r=20, t=16, b=44),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(color=INK_MUTED, size=12),
        hovermode="x unified",
        xaxis=dict(showgrid=False, linecolor=GRID),
        yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    return fig


def register_callbacks(app: Dash) -> None:
    @app.callback(
        Output("buffer-store", "data"),
        Output("bulk-load-status", "children"),
        Output("poll-interval", "disabled"),
        Output("view-mode", "data"),
        Input("poll-interval", "n_intervals"),
        Input("live-button", "n_clicks"),
        Input("bulk-load-button", "n_clicks"),
        State("buffer-store", "data"),
        State("view-mode", "data"),
        prevent_initial_call=True,
    )
    def update_buffer(_n_intervals, _live_clicks, _bulk_clicks, current_records, view_mode):
        trigger = ctx.triggered_id

        if trigger == "bulk-load-button":
            # Stop live refresh and show the whole shift at once.
            #
            # Sending every reading would be a 10 MB payload and 317,376 plotted
            # points, which locks the browser. Bucket by minute first, keeping each
            # minute's PEAK rather than its average: averaging hides the spikes
            # inside a minute, and the spikes are what stress a joint.
            full_df = db.cached_all()
            bucketed = (
                full_df.set_index("reading_time")[AXIS_COLUMNS]
                .resample(BULK_BUCKET)
                .max()
                .fillna(0.0)
                .reset_index()
            )
            status = (
                f"Whole shift: {len(full_df):,} readings from the database, "
                f"shown as {len(bucketed):,} per-minute peaks."
            )
            return _to_records(bucketed), status, True, "shift"

        if trigger == "live-button":
            # Resume live refresh from a clean slate.
            db.reset_cursor()
            return [], "Live: one reading every 2 seconds.", False, "live"

        # Interval tick. If the whole-shift view is up, leave it alone: this tick may
        # have been queued before the button disabled polling.
        if view_mode == "shift":
            raise PreventUpdate

        new_rows = db.fetch_next_batch()
        if new_rows.empty:
            raise PreventUpdate

        current = _from_records(current_records or [])
        combined = pd.concat([current, new_rows], ignore_index=True)
        combined = _trim_to_window(combined)
        # Only the columns the chart draws; id and inserted_at are dead weight.
        combined = combined[["reading_time", *AXIS_COLUMNS]]
        return _to_records(combined), "", False, "live"

    @app.callback(
        Output("live-status-chart", "figure"),
        Input("buffer-store", "data"),
    )
    def redraw_chart(records):
        df = _from_records(records)
        return _build_figure(df)
