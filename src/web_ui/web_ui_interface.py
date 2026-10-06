"""Entry point for the robot predictive-maintenance web dashboard.

MVP scope: a single "Live Status" tab (see live_status.py). Run directly:

    python src/web_ui/web_ui_interface.py
"""

from dash import Dash, html

import live_status

app = Dash(__name__, title="Robot Health Monitor")
app.layout = html.Div(
    [
        html.Div(
            [
                html.H1("Robot Health Monitor",
                        style={"margin": "0", "fontSize": "24px", "color": "#0b0b0b"}),
                html.Div(
                    "Kawasaki materials-handling robot · per-joint current · Group 4",
                    style={"color": "#52514e", "fontSize": "13px", "marginTop": "4px"},
                ),
            ],
            style={"maxWidth": "1180px", "margin": "0 auto",
                   "padding": "22px 20px 16px"},
        ),
        live_status.layout,
    ],
    style={"background": "#fcfcfb", "minHeight": "100vh",
           "fontFamily": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"},
)
live_status.register_callbacks(app)

if __name__ == "__main__":
    app.run(debug=True)
