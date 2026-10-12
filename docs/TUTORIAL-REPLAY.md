# Tutorial replay: NX textbook exercises in FreeCAD NX-Style

Four exercises from the NX notebook were replayed inside FreeCAD 1.1.4 with `python launch_nx.py --tutorial OUTDIR` (`--tutorials C,D` picks some), the way the books tell an NX user to work. The replay presses the same keys, clicks the NX-named ribbon buttons, clicks sketch points with MB1 in the graphics window, ends tools and accepts dialogs with MB2, and checks each feature by its volume.

- **A, The Adjuster** (Shih, *Parametric Modeling with Siemens NX*, ch. 2), in inches. The step list came from NotebookLM; its slot placement was ambiguous, so the replay cuts a 1.00 in wide, 0.75 in deep slot into the top of the vertical leg (the part stays one solid).
- **B, First part**: a hollow cylinder (Ø50/Ø30 × 50 mm) and a revolved cone (R25 × 50 mm). NotebookLM attributed it to the KIT course but cited Shih and Tickoo; treat it as a synthesised exercise.
- **C, Rod-Guide** (Shih ch. 9), in inches: a filleted 3.00 × 2.00 × 0.75 block with four holes, an At Angle datum plane, an offset datum plane, and a hole drilled from that datum. The step order follows the book's text; its sizes appear only in figures, so they are NotebookLM's reading. The angled upper block (C9) is skipped because its profile is figure-only.
- **D, Pulley with drawing** (Shih ch. 11), in inches: a revolved half section, Mirror Feature, a pattern leader hole, a 5× circular pattern, then a drawing with a right base view and a section view. The profile sizes (Ø4.00 × 1.00, hub Ø1.50, bore Ø0.75, web 0.25, five Ø0.50 holes on a 2.50 pitch circle) are again NotebookLM's reading of the figures.

Dimension values are applied through FreeCAD's API, the equivalent of typing them into Rapid Dimension. Everything else is real UI input.

**same** = NX steps work as written. **differs** = it works, but the FreeCAD way is different (explained). **skipped** = not replayed (reason given). **FAILED** = did not work. The final run had no FAILED steps: A 13 same / 5 differs, B 13 / 2, C 11 / 3 / 1 skipped, D 13 / 7.

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
| C1 | File > New (Ctrl+N), Model template, inches | Ctrl+N | **same** |  |
| C2 | Extrude (X), pick the XY plane | X key, plane row + MB2 | **same** | picked XY-plane (Base plane) |
| C3 | Rectangle (R) by 2 points around the origin | R key + 2 MB1 clicks + MB2 | **same** | tool True; 4 curves; ended True |
| C4 | Sketch Fillet (F), R0.25 on the four corners | F key; corners applied as values | **differs** | F starts FreeCAD's sketch fillet; the radius is typed after picking, not before as in NX |
| C5 | Circle (O): four Ø0.25 circles on the arc centres, Equal Radius | O key; values applied | **same** | Equal constraint exists in both |
| C6 | Finish Sketch, Extrude 0.75, OK | Ctrl+Q, 'lengthEdit' = 0.75 in, MB2 = OK | **same** | volume 4.3125 in^3, expected 4.3125; 1 solid(s) |
| C7 | Datum Plane, At Angle: front face | select face + ribbon 'Home > Datum > Datum Plane' | **same** | the datum is attached to the face; FreeCAD's attachment dialog opens |
| C8 | Angle -30° about the vertical axis, OK | 'attachmentOffsetPitch' = -30°, MB2 = OK | **differs** | plane at 30.00° to the face. NX picks the Z axis as hinge; FreeCAD rotates in the attachment offset about the face's own axes |
| C9 | Extrude the angled upper block on the datum plane (Unite, Symmetric 1.0) | - | **skipped** | the profile's dimensions are only in the book's figures |
| C10 | Datum Plane, At Distance: top face | select face + ribbon 'Home > Datum > Datum Plane' | **same** |  |
| C11 | Distance 0.75, OK | 'attachmentOffsetZ' = 0.75 in, MB2 = OK | **same** | datum plane at z = 1.5000 in (top face 0.75 + 0.75) |
| C12 | Hole, placed on the offset datum plane | select plane + ribbon 'Home › Feature > Hole' | **differs** | FreeCAD's Hole drills at circle centres in a sketch, so Hole starts a sketch on the plane (NX picks the point directly) |
| C13 | Place the hole centre at the WCS origin | O key + MB1 at the origin + MB2 | **same** | tool True; 1 curves; ended True |
| C14 | Hole: Simple, Ø0.25, Through Body, OK | dialog open True; 'Diameter' = 0.25 in, 'Through all', MB2 = OK | **same** | volume 4.2757 in^3, expected 4.2757; 1 solid(s) |
| C15 | The finished part is shown in the graphics window | render of the graphics window | **same** | 21.6% of the view shows the part |
| D1 | File > New (Ctrl+N), Model template | Ctrl+N | **same** |  |
| D2 | Revolve, nothing selected | ribbon 'Home › Feature > Revolve' | **same** |  |
| D3 | Pick the XY plane of the datum CSYS | plane row + MB2 | **same** | XY-plane (Base plane) |
| D4 | Profile (Z): closed half cross-section, MB2 | Z key + 9 MB1 clicks + MB2 | **same** | tool True; 8 curves; ended True |
| D5 | Rapid Dimension: profile sizes | values applied | **differs** | same tool; no dynamic dimensions |
| D6 | Specify Vector = X axis through the origin, 0..360°, OK | axis 'Base X-axis', MB2 = OK | **same** | volume 3.1170 in^3, expected 3.1170; 1 solid(s); NX picks the axis in the graphics window, FreeCAD lists it in the dialog |
| D7 | Mirror Feature: select the revolved feature, MB2 to proceed | feature selected + ribbon 'Home › Pattern > Mirror Feature' | **differs** | selecting first and then starting Mirror Feature replaces NX's 'select, then MB2' |
| D8 | Plane = the back face (on the YZ plane), OK; Unite | plane 'Base YZ-plane', MB2 = OK | **same** | volume 6.2341 in^3, expected 6.2341; 1 solid(s); inside a Body the mirror unites by itself, so NX's separate Unite step is not needed |
| D9 | Pattern leader: Extrude on the front face of the web, Subtract | select face + ribbon 'Home › Feature > Extrude (Subtract)' | **differs** | subtracting extrude is its own button in FreeCAD |
| D10 | Circle Ø0.50 on the 2.50 pitch circle | O key + MB1 clicks + MB2; values applied | **same** | tool True; 1 curves |
| D11 | Reverse Direction, End = Through All, OK | 'Through all', MB2 = OK | **same** | volume 6.1850 in^3, expected 6.1850; 1 solid(s); no Reverse needed in FreeCAD |
| D12 | Pattern Feature, Layout = Circular | leader selected + ribbon 'Home › Pattern > Circular Pattern' | **differs** | NX has one Pattern Feature with a Layout list; FreeCAD has separate linear and circular buttons |
| D13 | Axis X, Count and Span: 5 over 360°, OK | axis 'Base X-axis', 'spinOccurrences' = 5, MB2 = OK | **same** | volume 5.9887 in^3, expected 5.9887; 1 solid(s) |
| D14 | The finished part is shown in the graphics window | render of the graphics window | **same** | 12.6% of the view shows the part |
| D15 | File > Drafting (Ctrl+Shift+D) | Ctrl+Shift+D | **same** | TechDrawWorkbench |
| D16 | New sheet, A-size, 1:1 | ribbon 'Home › Drawing > New Sheet' | **differs** | FreeCAD's default template Default_Template_A4_Landscape.svg; an ANSI A sheet is one template choice away (Sheet from Template) |
| D17 | Base View: Right view of the pulley | body selected + ribbon 'Home › View > Base View'; dialog closed with MB2 | **same** | 1 view(s) on the sheet; direction set to Right (+X) |
| D18 | Add a projected view, select it, Delete key | Base View again + Delete key | **differs** | views 2 -> 1. NX drags projected views off the base view; FreeCAD's Projected View is a projection group, so a second Base View stood in for it |
| D19 | Section View through the centre of the base view | base view selected + ribbon 'Home › View > Section View', direction 'pbLeft', MB2 = OK | **same** | 1 section view(s), 42 visible edges |
| D20 | Drag the section to the right of the base view, MB1 to place | X/Y of the section set | **differs** | FreeCAD places the section on top of the base view; it is moved afterwards (placed at x = 224.7 mm, base at 148.5 mm) |

## What the replay changed in NXStyle

- **Extrude-first workflow (NX):** Extrude (X) or Revolve with nothing selected starts a sketch on the plane or face you pick. Finish Sketch (Ctrl+Q) then continues straight into the Extrude or Revolve dialog. With a sketch already selected, the feature starts at once. Extrude (Subtract) and Revolve (Subtract) work the same way.
- **NX Model template:** a new, empty part starts with a Body (setting `new_part_datum`). Its datum planes appear when you pick a sketch plane.
- **MB2 ends the active sketch tool**, as in NX.
- **MB2 rotate/pan/zoom** now reads Shift/Ctrl from the mouse event. Before, a stale global modifier state after Ctrl shortcuts could turn MB2 rotate into a zoom.
- **Hole on a plane (C):** Hole with a datum plane or face selected starts a sketch there, and Finish Sketch continues into the Hole dialog, as Extrude does.
- **MB2 = OK on drawing sheets (D):** a still middle click on a TechDraw sheet now presses OK in the open dialog (Base View, Section View); MB2 drag still pans.

![Tutorial D drawing: right view with the five holes, section A-A beside it](tutorial-D-drawing.png)

## Differences that remain (FreeCAD behaviour)

- Units are set per document or in Preferences, not in the New dialog.
- FreeCAD asks for the sketch plane in the Dialog panel; NX lets you click it in the graphics window. Clicking the plane in the 3D view also works in FreeCAD.
- No NX dynamic dimensions on click, and no 'scale the whole sketch to the first dimension' prompt. Rapid Dimension (D) opens FreeCAD's dimension tool.
- Extrude has no Boolean option: subtracting is its own button, Extrude (Subtract). Features in one Body unite automatically. Reverse Direction is rarely needed because a subtracting extrude cuts into the solid by default.
- Files are .FCStd, not .prt.
- Datum planes: FreeCAD's At Angle plane rotates about the face's own axes in the attachment offset; NX lets you pick the hinge axis.
- Hole drills at circle centres in a sketch; NX places hole points directly.
- Mirror Feature: select the feature first, then start the command. Inside a Body the mirror unites by itself.
- NX has one Pattern Feature with a Layout list; FreeCAD has separate Linear Pattern and Circular Pattern buttons. The axis is chosen from a list in the dialog.
- Drawings: FreeCAD's default sheet is A4 (an ANSI A template is available). Projected View is a projection group rather than views dragged off the base view. A new section view lands on top of its base view and is moved afterwards.

## Resolved: part missing from the 3D view

Earlier runs showed finished parts in the Part Navigator but not in the 3D view, on the hidden desktop and on a normal screen alike. Bisection traced it to the Body's origin planes. In **plain FreeCAD 1.1.4**, without NXStyle, a Body whose origin stays visible disappears from the view after a view fit. NXStyle's template had kept the origin on to mimic NX's datum CSYS. It now leaves the origin hidden, and FreeCAD still shows the planes while you pick one. The final run passes every step on the hidden desktop and on a normal screen.

A separate crash while closing a document came from a test-only probe that held Python references into FreeCAD's scene graph; that probe is gone.

## Resolved: runaway memory in Tutorial D

The first runs of Tutorial D made FreeCAD request about 19 GB at the Circular Pattern step. The cause was the replay's own field helper, not NXStyle: FreeCAD's occurrence count field is a `Gui::UIntSpinBox`, which stores unsigned values offset by 2^31 inside a Qt `QSpinBox`. Setting it from Python with `QSpinBox.setValue(5)` bypasses that mapping and stores 2^31 + 5, clamped to 2147483647 occurrences, so FreeCAD tried to build two billion pattern copies. Typing the number, as a user does, maps correctly. The replay now types and interprets the text, and refuses to press OK on a pattern whose count is not the one requested. Every `--tutorial` and `--smoke-test` run also has a 4 GB memory ceiling (`--max-memory-gb`); the full A–D replay peaks at about 2.7 GB. Each step start goes to `OUTDIR/progress.log` with FreeCAD's committed memory, so a run stopped at the ceiling still shows where it was.
