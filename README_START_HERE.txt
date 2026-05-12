FINAL av pm - Project AV PM Performance System

This is the complete current package, not a patch.

WHAT IS INCLUDED
- av_pm_reporter.py: PM weekly report app.
- av_master_dashboard.py: host/master dashboard app.
- av_common.py: shared logic, official division colors, metrics, JSON helpers.
- cleanup_old_demo_reports.py: removes old fake demo reports from previous prototypes.
- requirements.txt: Python dependencies.
- run_pm_reporter.bat: opens the PM report app.
- run_master_dashboard.bat: opens the master dashboard.
- install_dependencies.bat: installs dependencies using the active Python/Conda environment.
- reports_outbox/: final JSON reports created by PMs.
- reports_inbox/: JSON reports collected by the host/master dashboard.
- reports_archive/: optional archive folder.
- report_drafts/: PM draft autosaves and manual saves.

OFFICIAL DIVISION COLORS - DO NOT OVERRIDE
- Power and Electrical Systems: yellow
- Vehicle Design & Structures: blue
- Software & Hardware: red
- Astrobiology: green
- Robotic Arm: purple

GENERAL UI THEME
- Black/white futuristic base.
- Red/blue accent scheme for general UI.
- Division-specific components use the official division colors above.

WINDOWS / MINICONDA SETUP
1. Open Miniconda Prompt.
2. Go into this folder:
   cd path\to\FINAL av pm
3. Create and activate the environment:
   conda create -n av-performance python=3.11 -y
   conda activate av-performance
4. Install dependencies:
   pip install -r requirements.txt

RUNNING THE APPS
PM side:
   streamlit run av_pm_reporter.py
or double-click:
   run_pm_reporter.bat

Master dashboard:
   streamlit run av_master_dashboard.py
or double-click:
   run_master_dashboard.bat

DATA FLOW
PMs use av_pm_reporter.py.
Drafts are saved in report_drafts/ so work is not lost.
Final submitted reports are saved in reports_outbox/.
The master dashboard reads JSON reports from reports_inbox/ and reports_outbox/.
Incomplete drafts are NOT read by the dashboard.

IMPORTANT
This package has no fake placeholder reports included. If old fake reports are still in your previous folder, run:
   python cleanup_old_demo_reports.py
or use this clean folder directly.

