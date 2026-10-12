# Tutorial replay: NX textbook exercises in FreeCAD NX-Style

Two beginner exercises from the NX notebook were replayed inside FreeCAD 1.1.4 with `python launch_nx.py --tutorial OUTDIR`, the way the books tell an NX user to work. The replay presses the same keys, clicks the NX-named ribbon buttons, clicks sketch points with MB1 in the graphics window, ends tools and accepts dialogs with MB2, and checks each feature by its volume.

- **A, The Adjuster** (Shih, *Parametric Modeling with Siemens NX*, ch. 2), in inches. The step list came from NotebookLM; its slot placement was ambiguous, so the replay cuts a 1.00 in wide, 0.75 in deep slot into the top of the vertical leg (the part stays one solid).
- **B, First part**: a hollow cylinder (Ø50/Ø30 × 50 mm) and a revolved cone (R25 × 50 mm). NotebookLM attributed it to the KIT course but cited Shih and Tickoo; treat it as a synthesised exercise.

Dimension values are applied through FreeCAD's API, the equivalent of typing them into Rapid Dimension. Everything else is real UI input.

**same** = NX steps work as written. **differs** = it works, but the FreeCAD way is different (explained). **FAILED** = did not work.

| # | NX step | How it was replayed | Result | Detail |
|---|---|---|---|---|
| A1 | File > New (Ctrl+N), Model template | Ctrl+N | **same** | new document ['Unnamed'] with a Body; its datum planes appear when a plane is picked (kept hidden otherwise: FreeCAD 1.1.4 hides the part when they stay on) |
| A2 | Units: Inches in the New dialog | Document > Unit system | **differs** | set per document in FreeCAD (Imperial decimal (in, lb)), not in the New dialog |
| A3 | Extrude (X) with nothing selected | X key | **same** | FreeCAD asks for the sketch plane in the Dialog panel; NX asks in the graphics window |
| A4 | Pick the XY plane, accept with MB2 | plane row in the Dialog panel + MB2 click | **same** | picked XY-plane (Base plane); sketch in edit: Sketch |
| A5 | Profile (Z), six MB1 clicks for the L outline | Z key + MB1 clicks in the graphics window | **same** | tool active True; 6 curves drawn |
| A6 | MB2 ends Profile | MB2 click | **same** | tool ended = True |
| A7 | Rapid Dimension (D): 2.5 width, 2.5 height, 0.75 legs | D key, values applied | **differs** | D starts FreeCAD's Dimension tool. FreeCAD does not show NX's dynamic dimensions on click, and there is no 'scale the whole sketch to the first dimension?' prompt |
| A8 | Finish Sketch (Ctrl+Q) returns to the Extrude dialog | Ctrl+Q | **same** | Extrude dialog open = True; modals [] |
| A9 | Extrude: End = Value 2.5, Boolean None, OK | typed into 'lengthEdit', MB2 = OK | **same** | volume 7.9687 in^3, expected 7.9688 |
| A10 | Extrude, pick the top face as sketch plane, Boolean Subtract | select face + ribbon 'Home › Feature > Extrude (Subtract)' | **differs** | FreeCAD has no Boolean option in Extrude: the subtracting extrude is its own button (Home > Feature > Extrude (Subtract)) |
| A11 | Rectangle (R), two MB1 clicks, MB2 | R key + MB1 clicks + MB2 | **same** | tool active True; 4 curves |
| A12 | Rapid Dimension: 0.50 from edge, 1.00 wide, 0.75 deep | values applied | **differs** | as in step 6: same tool, no NX dynamic dimensions |
| A13 | Finish Sketch returns to the (subtract) Extrude dialog | Ctrl+Q | **same** | dialog open = True |
| A14 | Reverse Direction into the solid | - | **differs** | not needed: FreeCAD's subtracting extrude cuts into the solid by default |
| A15 | Slot depth 0.75, OK | 'lengthEdit' = 0.75 in, MB2 = OK | **same** | volume 7.4062 in^3, expected 7.4062; 1 solid(s) |
| A16 | The finished part is shown in the graphics window | render of the graphics window | **same** | 26.7% of the view shows the part |
| A17 | Save (Ctrl+S) | Ctrl+S is bound to Save (tested by the self-test); file saved | **same** | saved as Adjuster.FCStd (FreeCAD format, not .prt) |
| A18 | Reopened part is shown | render of the graphics window | **same** | 26.7% of the view shows the part |
| B1 | File > New (Ctrl+N), Model template, mm | Ctrl+N | **same** | new document ['Unnamed'] |
| B2 | Extrude (X), pick the XC-YC plane | X key, plane row + MB2 | **same** | picked XY-plane (Base plane) |
| B3 | Circle (O): two circles at the origin, MB2 | O key + MB1 clicks + MB2 | **same** | tool True; 2 circles; ended True |
| B4 | Rapid Dimension: diameters 50 and 30 | values applied | **differs** | same tool; values typed in FreeCAD's dimension field |
| B5 | Finish Sketch, Extrude 0 to 50 mm, OK | Ctrl+Q, 'lengthEdit' = 50, MB2 = OK | **same** | volume 62831.9 mm^3, expected 62831.9 |
| B6 | Revolve (ribbon) | ribbon 'Home › Feature > Revolve' | **same** | nothing selected: sketch first, as with Extrude |
| B7 | Pick the YC-ZC plane | plane row + MB2 | **same** | picked YZ-plane (Base plane) |
| B8 | Line (L): right triangle on the axis, MB2 | L key + MB1 clicks + MB2 | **same** | tool True; 3 lines |
| B9 | Rapid Dimension: height 50, radius 25 | values applied | **differs** | same tool |
| B10 | Finish Sketch returns to Revolve; axis = Z, 0..360 deg | Ctrl+Q | **same** | dialog open True; default axis ['V_Axis'] (sketch V axis = Z) |
| B11 | Boolean Unite, OK | MB2 = OK | **same** | volume 95556.8 mm^3, expected 95556.8; features in one Body unite automatically |
| B12 | Hold MB2 and drag to rotate | MB2 drag | **same** |  |
| B13 | F8 snaps to the nearest standard view | F8 key | **same** | view Vector (0.0, 1.0, 0.0) |
| B14 | The finished part is shown in the graphics window | render of the graphics window | **same** | 11.3% of the view shows the part |
| B15 | Save (Ctrl+S) | file saved | **same** | FirstPart.FCStd |

## What the replay changed in NXStyle

- **Extrude-first workflow (NX):** Extrude (X) or Revolve with nothing selected starts a sketch on the plane or face you pick. Finish Sketch (Ctrl+Q) then continues straight into the Extrude or Revolve dialog. With a sketch already selected, the feature starts at once. Extrude (Subtract) and Revolve (Subtract) work the same way.
- **NX Model template:** a new, empty part starts with a Body (setting `new_part_datum`). Its datum planes appear when you pick a sketch plane.
- **MB2 ends the active sketch tool**, as in NX.
- **MB2 rotate/pan/zoom** now reads Shift/Ctrl from the mouse event. Before, a stale global modifier state after Ctrl shortcuts could turn MB2 rotate into a zoom.

## Differences that remain (FreeCAD behaviour)

- Units are set per document or in Preferences, not in the New dialog.
- FreeCAD asks for the sketch plane in the Dialog panel; NX lets you click it in the graphics window. Clicking the plane in the 3D view also works in FreeCAD.
- No NX dynamic dimensions on click, and no 'scale the whole sketch to the first dimension' prompt. Rapid Dimension (D) opens FreeCAD's dimension tool.
- Extrude has no Boolean option: subtracting is its own button, Extrude (Subtract). Features in one Body unite automatically. Reverse Direction is rarely needed because a subtracting extrude cuts into the solid by default.
- Files are .FCStd, not .prt.

## Resolved: part missing from the 3D view

Earlier runs showed finished parts in the Part Navigator but not in the 3D view, on the hidden desktop and on a normal screen alike. Bisection traced it to the Body's origin planes. In **plain FreeCAD 1.1.4**, without NXStyle, a Body whose origin stays visible disappears from the view after a view fit. NXStyle's template had kept the origin on to mimic NX's datum CSYS. It now leaves the origin hidden, and FreeCAD still shows the planes while you pick one. The final run passes every step on the hidden desktop and on a normal screen.

A separate crash while closing a document came from a test-only probe that held Python references into FreeCAD's scene graph; that probe is gone.
