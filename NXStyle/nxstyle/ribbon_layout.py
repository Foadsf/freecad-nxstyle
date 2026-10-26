# SPDX-License-Identifier: LGPL-2.1-or-later
"""How a ribbon page fits its width, the user's layout choices, and the window sizes it must fit.

No Qt and no FreeCAD here, so the unit tests can check it; ``ribbon.py`` measures the widgets and
applies the plan.

A page that is too narrow gives up room in stages:

1. compact:   small buttons show their icon only (the name stays in the tooltip and accessible name);
2. collapsed: the group becomes one button whose menu lists the group's commands;
3. overflow:  the group moves into the page's More menu.

The groups are taken in tiers, least important first: rank (a group holding an essential command
ranks 10), and a group the user set to Keep Expanded after every other. Within a tier every group
goes compact, from the right, then collapsed; the next tier is touched only after that, and the
More menu comes last. A group set to Always Collapsed starts collapsed. A plan is the shortest
prefix of that one sequence that fits, so a wider window never reduces a group more. Every command
stays reachable at any width, and nothing is left half visible.
"""

import json
import os

FULL, COMPACT, COLLAPSED, OVERFLOW = "full", "compact", "collapsed", "overflow"
STAGES = (FULL, COMPACT, COLLAPSED, OVERFLOW)
AUTO, EXPANDED = "auto", "expanded"           # user choices; COLLAPSED is the third
PREFERENCES = (AUTO, EXPANDED, COLLAPSED)
ESSENTIAL_RANK = 10                           # default rank of a group holding an essential command


class GroupFit:
    """What the planner needs to know about one group: its width in each stage (separator
    included), rank, position on the page and the user's choice."""

    def __init__(self, widths, rank=0, index=0, preference=AUTO):
        self.widths = widths
        self.rank = rank
        self.index = index
        self.preference = preference


def reduction_order(groups):
    """Groups in the order they give up space: Keep Expanded last, then lowest rank, then rightmost."""
    return sorted(groups, key=lambda g: (g.preference == EXPANDED, g.rank, -g.index))


def plan(groups, available, base=0, overflow_width=0):
    """Stage per group (list, in page order) so the page fits ``available`` pixels.

    ``base`` is the page's own margins; ``overflow_width`` the More button's width, counted once a
    group has moved into it. If even all groups in the More menu do not fit, everything is there."""
    stage = [COLLAPSED if g.preference == COLLAPSED else FULL for g in groups]
    pos = {id(g): i for i, g in enumerate(groups)}

    def total():
        used = sum(g.widths[s] for g, s in zip(groups, stage) if s != OVERFLOW)
        return base + used + (overflow_width if OVERFLOW in stage else 0)

    for g, target in reduction_steps(groups):
        if total() <= available:
            return stage
        i = pos[id(g)]
        if STAGES.index(stage[i]) < STAGES.index(target):
            stage[i] = target
    return stage


def tier(g):
    return (g.preference == EXPANDED, g.rank)


def reduction_steps(groups):
    """The fixed sequence of (group, stage) steps; a plan is the shortest prefix that fits, so more room
    never reduces a group more. Tier by tier, least important first: every group of the tier goes compact,
    then collapsed; only then is the next tier touched. Moving groups to the More menu comes last."""
    order = reduction_order(groups)
    steps = []
    for t in sorted({tier(g) for g in groups}):
        members = [g for g in order if tier(g) == t]
        steps += [(g, COMPACT) for g in members] + [(g, COLLAPSED) for g in members]
    return steps + [(g, OVERFLOW) for g in order]


def plan_width(groups, stage, base=0, overflow_width=0):
    used = sum(g.widths[s] for g, s in zip(groups, stage) if s != OVERFLOW)
    return base + used + (overflow_width if OVERFLOW in stage else 0)


class LayoutStore:
    """The user's ribbon layout, kept in the profile's config folder (``nxstyle.ribbon.json``):
    per application, tab and group the choice Automatic / Keep Expanded / Always Collapsed, and
    whether the ribbon is minimised. Written as soon as it changes, so it survives a crash."""

    FILE = "nxstyle.ribbon.json"
    VERSION = 1

    def __init__(self, folder):
        self.path = os.path.join(folder, self.FILE) if folder else ""
        self.data = {"version": self.VERSION, "groups": {}, "minimized": False}
        self.error = ""
        if self.path and os.path.isfile(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict) or not isinstance(loaded.get("groups", {}), dict):
                    raise ValueError("not a ribbon layout")
                self.data["groups"] = {k: v for k, v in loaded.get("groups", {}).items() if v in PREFERENCES}
                self.data["minimized"] = bool(loaded.get("minimized", False))
            except (OSError, ValueError) as e:
                self.error = f"ignoring unreadable {self.path}: {e}"

    @staticmethod
    def key(app, tab, group):
        return f"{app}/{tab}/{group}"

    def preference(self, app, tab, group):
        return self.data["groups"].get(self.key(app, tab, group), AUTO)

    def set_preference(self, app, tab, group, value):
        if value not in PREFERENCES:
            raise ValueError(value)
        k = self.key(app, tab, group)
        if value == AUTO:
            self.data["groups"].pop(k, None)
        else:
            self.data["groups"][k] = value
        self.save()

    @property
    def minimized(self):
        return self.data["minimized"]

    def set_minimized(self, value):
        self.data["minimized"] = bool(value)
        self.save()

    def reset(self):
        self.data["groups"] = {}
        self.data["minimized"] = False
        self.save()

    def save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError as e:
            self.error = f"could not save {self.path}: {e}"


# ------------------------------------------------------------------ qualification matrix
RESOLUTIONS = ((1366, 768), (1920, 1080))
SCALES = (1.0, 1.25, 1.5, 2.0)
TASKBAR = 48        # Windows 11 taskbar, logical pixels at every scale
TITLE_BAR = 31      # the main window's title bar, logical pixels


def matrix_cells(resolutions=RESOLUTIONS, scales=SCALES):
    """The maximised main window's client area, in Qt's logical pixels, for each screen and scale.

    With Qt's high-DPI scaling a window is laid out in logical pixels (physical / scale) and fonts
    and icons scale with it, so a cell is reproduced by giving the window that logical size."""
    cells = []
    for w, h in resolutions:
        for s in scales:
            cells.append({"name": f"{w}x{h}@{round(s * 100)}%", "screen": (w, h), "scale": s,
                          "window": (int(w / s), int(h / s) - TASKBAR - TITLE_BAR)})
    return cells
