# Keyboard shortcuts

The NX bindings follow [Foadsf/NXtips](https://github.com/Foadsf/NXtips), plus Ctrl+T (Move Object) from the NX textbooks. Every key below was pressed through Qt's real shortcut system by the self-test (`launch_nx.py --smoke-test`) on FreeCAD 1.0.2 and 1.1.4 and reached its FreeCAD command, with no other action holding the key. Sketch keys were tested in sketch edit mode.

One difference from the NX textbooks: NXtips binds **F4 to Touch Mode**, while two textbooks give F4 as Repeat Command. This project follows NXtips; Repeat Command stays on the Quick Access Toolbar.

| NX command | Key | FreeCAD command | Where | Note |
|---|---|---|---|---|
| New | <kbd>Ctrl</kbd>+<kbd>N</kbd> | `Std_New` | anywhere |  |
| Open | <kbd>Ctrl</kbd>+<kbd>O</kbd> | `Std_Open` | anywhere |  |
| Save | <kbd>Ctrl</kbd>+<kbd>S</kbd> | `Std_Save` | anywhere |  |
| Save As | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>A</kbd> | `Std_SaveAs` | anywhere |  |
| Save as New Item Type | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>I</kbd> | `Std_SaveCopy` | anywhere | Teamcenter item types do not exist in FreeCAD; saves a copy under a new name |
| Save as Non-Master Parts | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd> | (explains why) | anywhere | Non-master parts are a Teamcenter/NX concept with no FreeCAD equivalent. Use File > Save a Copy, or link the part into a new document (Std_LinkMake). |
| Plot | <kbd>Ctrl</kbd>+<kbd>P</kbd> | `Std_Print` | anywhere |  |
| Execute NXOpen | <kbd>Ctrl</kbd>+<kbd>U</kbd> | `Std_DlgMacroExecute` | anywhere | runs a FreeCAD Python macro |
| Execute GRIP | <kbd>Ctrl</kbd>+<kbd>G</kbd> | `Std_DlgMacroExecute` | anywhere | GRIP does not exist in FreeCAD; opens the macro (Python) runner |
| Execute Debug GRIP | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>G</kbd> | `Std_MacroStartDebug` | anywhere | debugs the macro open in FreeCAD's macro editor |
| Undo | <kbd>Ctrl</kbd>+<kbd>Z</kbd> | `Std_Undo` | anywhere |  |
| Redo | <kbd>Ctrl</kbd>+<kbd>Y</kbd> | `Std_Redo` | anywhere |  |
| Cut | <kbd>Ctrl</kbd>+<kbd>X</kbd> | `Std_Cut` | anywhere |  |
| Copy | <kbd>Ctrl</kbd>+<kbd>C</kbd> | `Std_Copy` | anywhere |  |
| Paste | <kbd>Ctrl</kbd>+<kbd>V</kbd> | `Std_Paste` | anywhere |  |
| Paste Special | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>V</kbd> | `Std_DuplicateSelection` | anywhere | FreeCAD's Duplicate Selection (copy with dependency options) |
| Delete | <kbd>Ctrl</kbd>+<kbd>D</kbd> | `Std_Delete` | anywhere | the Delete key still works |
| Front View | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>F</kbd> | `Std_ViewFront` | anywhere |  |
| Top View | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>T</kbd> | `Std_ViewTop` | anywhere |  |
| Left View | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>L</kbd> | `Std_ViewLeft` | anywhere |  |
| Right View | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>R</kbd> | `Std_ViewRight` | anywhere |  |
| Trimetric View | <kbd>Home</kbd> | `Std_ViewTrimetric` | anywhere |  |
| Isometric View | <kbd>End</kbd> | `Std_ViewIsometric` | anywhere |  |
| Orient to Active Sketch | <kbd>Shift</kbd>+<kbd>F8</kbd> | `Sketcher_ViewSketch` | sketch |  |
| Snap to Closest Standard View | <kbd>F8</kbd> | `NXStyle_SnapView` | anywhere |  |
| Fit | <kbd>Ctrl</kbd>+<kbd>F</kbd> | `Std_ViewFitAll` | anywhere |  |
| Zoom | <kbd>F6</kbd> | `Std_ViewBoxZoom` | anywhere | drag a rectangle to zoom |
| Rotate | <kbd>F7</kbd> | `NXStyle_RotateMode` | anywhere | MB1 drag rotates until Esc, MB2 or MB3 |
| Refresh | <kbd>F5</kbd> | `NXStyle_Refresh` | anywhere | redraws the view; recompute stays on FreeCAD's Ctrl+R |
| Toggle WCS Display | <kbd>W</kbd> | `Std_AxisCross` | anywhere | FreeCAD's axis cross at the origin; FreeCAD has no movable WCS |
| Edit Section | <kbd>Ctrl</kbd>+<kbd>H</kbd> | `Part_SectionCut` | anywhere |  |
| Toggle Full Screen | <kbd>Alt</kbd>+<kbd>Return</kbd> | `Std_MainFullscreen` | anywhere |  |
| Extrude | <kbd>X</kbd> | `PartDesign_Pad` | anywhere |  |
| Move Object | <kbd>Ctrl</kbd>+<kbd>T</kbd> | `NXStyle_MoveObject` | anywhere | Distance, Angle, Point to Point; Dynamic is FreeCAD's Transform dragger |
| Profile | <kbd>Z</kbd> | `Sketcher_CreatePolyline` | sketch |  |
| Rectangle | <kbd>R</kbd> | `Sketcher_CreateRectangle` | sketch |  |
| Line | <kbd>L</kbd> | `Sketcher_CreateLine` | sketch |  |
| Arc | <kbd>A</kbd> | `Sketcher_CreateArc` | sketch |  |
| Circle | <kbd>O</kbd> | `Sketcher_CreateCircle` | sketch |  |
| Polygon | <kbd>P</kbd> | `Sketcher_CreateRegularPolygon` | sketch |  |
| Studio Spline | <kbd>S</kbd> | `Sketcher_CreateBSplineByInterpolation` | sketch | Type Through Points; By Poles is "From control points" in the tool's drop-down; MB2 ends it |
| Quick Trim | <kbd>T</kbd> | `Sketcher_Trimming` | sketch |  |
| Quick Extend | <kbd>E</kbd> | `Sketcher_Extend` | sketch |  |
| Fillet | <kbd>F</kbd> | `Sketcher_CreateFillet` | sketch |  |
| Rapid Dimension | <kbd>D</kbd> | `Sketcher_Dimension` | sketch |  |
| Geometric Constraints | <kbd>C</kbd> | `NXStyle_GeometricConstraints` | sketch | NX's gallery as a menu; each choice runs FreeCAD's tool on the selection |
| Finish Sketch | <kbd>Ctrl</kbd>+<kbd>Q</kbd> | `Sketcher_LeaveSketch` | sketch |  |
| Hide | <kbd>Ctrl</kbd>+<kbd>B</kbd> | `NXStyle_Hide` (`Std_HideSelection` outside a sketch) | anywhere | in a sketch: the selected dimensions and constraints (FreeCAD's virtual space) |
| Show and Hide Panel | <kbd>Ctrl</kbd>+<kbd>W</kbd> | `NXStyle_ShowHide` | anywhere |  |
| Immediate Hide | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>I</kbd> | `NXStyle_ImmediateHide` | anywhere | pick objects to hide them; Esc to finish |
| Show Panel | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>K</kbd> | `NXStyle_Show` (`Std_ShowSelection` outside a sketch) | anywhere | shows the objects selected in the Part Navigator (in a sketch, the dimensions selected in the constraint list); with nothing selected, a list of the hidden objects to pick from |
| Show All | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>U</kbd> | `NXStyle_ShowAll` (and `Std_ShowObjects`) | anywhere | in a sketch, the hidden dimensions and constraints too |
| Invert Show/Hidden | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>B</kbd> | `NXStyle_InvertVisibility` | anywhere |  |
| Edit Display | <kbd>Ctrl</kbd>+<kbd>J</kbd> | `Std_SetAppearance` | anywhere |  |
| Object Information | <kbd>Ctrl</kbd>+<kbd>I</kbd> | `NXStyle_ObjectInfo` | anywhere |  |
| Modeling | <kbd>Ctrl</kbd>+<kbd>M</kbd> | `NXStyle_App_modeling` | anywhere |  |
| Sheet Metal | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> | `NXStyle_App_sheet_metal` | anywhere | Opens the Sheet Metal application on FreeCAD's SheetMetal add-on, which NXStyle bundles; without the add-on the key explains how to get it |
| Drafting | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>D</kbd> | `NXStyle_App_drafting` | anywhere |  |
| Layout | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Y</kbd> | `NXStyle_App_draft` | anywhere | FreeCAD's Draft 2D workbench |
| Shape Studio | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>S</kbd> | `NXStyle_App_shape_studio` | anywhere | FreeCAD's Surface workbench |
| Customize | <kbd>Ctrl</kbd>+<kbd>1</kbd> | `Std_DlgCustomize` | anywhere |  |
| User Interface Preferences | <kbd>Ctrl</kbd>+<kbd>2</kbd> | `Std_DlgPreferences` | anywhere |  |
| Layer Settings | <kbd>Ctrl</kbd>+<kbd>L</kbd> | `Draft_LayerManager` | anywhere | FreeCAD's Draft layer manager |
| Expressions | <kbd>Ctrl</kbd>+<kbd>E</kbd> | `NXStyle_Expressions` | anywhere | a spreadsheet named Expressions |
| Touch Mode | <kbd>F4</kbd> | `NXStyle_TouchMode` | anywhere | larger ribbon and bar icons |

## Keyboard access (NX-Style's own keys, not NX defaults)

These ten keys let the whole interface be worked without a mouse. No FreeCAD command holds them; the self-test fails if one takes a FreeCAD binding. With `"nx_shortcuts": false` they are not assigned either. See the documentation's *Keyboard shortcuts* page for the keys inside each area.

| Action | Key | Command |
|---|---|---|
| Command Finder | <kbd>Alt</kbd>+<kbd>Q</kbd> | `NXStyle_CommandFinder` |
| Focus the ribbon tabs | <kbd>Alt</kbd>+<kbd>0</kbd> | `NXStyle_FocusRibbon` |
| Focus the Part Navigator | <kbd>Alt</kbd>+<kbd>1</kbd> | `NXStyle_FocusNavigator` |
| Focus the Task Panel | <kbd>Alt</kbd>+<kbd>2</kbd> | `NXStyle_FocusTasks` |
| Focus the graphics view | <kbd>Alt</kbd>+<kbd>3</kbd> | `NXStyle_FocusView` |
| Focus the Resource Bar | <kbd>Alt</kbd>+<kbd>4</kbd> | `NXStyle_FocusResourceBar` |
| Focus the Selection Bar | <kbd>Alt</kbd>+<kbd>5</kbd> | `NXStyle_FocusSelectionBar` |
| Select geometry by name | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Space</kbd> | `NXStyle_SelectGeometry` |
| Keyboard pointer on/off | <kbd>F12</kbd> | `NXStyle_KeyboardPointer` |
| Keyboard access help | <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>K</kbd> | `NXStyle_KeyboardHelp` |

## FreeCAD keys the NX bindings take

An NX key also takes FreeCAD's key sequences that start with it (FreeCAD's two-key chords such as `S, B`), because Qt would otherwise wait for the second key. `"nx_shortcuts": false` gives them all back. The self-test lists them; this list is from a run with nine workbenches loaded (FreeCAD 1.1.4, 2026-11-02):

| NX key | FreeCAD bindings it takes |
|---|---|
| A | Assembly_CreateAssembly; Draft_Arc (A, R), Draft_ArcTools (A, R / A, T), Draft_Arc_3Points (A, T); Sketcher_ConstrainHorVer |
| C | Assembly_CreateJointCylindrical; Draft_Circle (C, I), Draft_Clone (C, L), Draft_ToggleConstructionMode (C, M); Part_SelectFilter (C, S); Sketcher_ConstrainCoincidentUnified |
| D | Assembly_CreateJointDistance; Draft_Dimension (D, I), Draft_Downgrade (D, N), Draft_Edit (D, E), Draft_Label (D, L); TechDraw_Dimension |
| E | Assembly_CreateView; Draft_Ellipse (E, L); Part_SelectFilter (E, S); Sketcher_ConstrainEqual |
| F | Assembly_CreateJointFixed; Draft_Facebinder (F, F), Draft_Fillet (F, I); FEM_PostFilterGlyph (F, G); Part_SelectFilter (F, S) |
| L | Assembly_CreateJointGearBelt; Draft_Line (L, I); Sketcher_ConstrainDistanceX |
| O | Assembly_CreateBom; Draft_Offset (O, S); Sketcher_ConstrainPointOnObject |
| P | Assembly_Insert, Assembly_InsertNewPart; Draft_Polygon (P, G), Draft_Wire (P, L); Sketcher_ConstrainParallel |
| R | Assembly_CreateJointRevolute; Draft_Rectangle (R, E), Draft_Rotate (R, O); FEM_ResultShow (R, S), FEM_ResultsPurge (R, P); Sketcher_CompConstrainRadDia |
| S | Assembly_CreateJointSlider; Draft_Scale, Draft_SetStyle, Draft_Split, Draft_Stretch (S, …); FEM analysis and solver chords (S, …); Sketcher_ConstrainSymmetric; Std_LinkSelectLinked (S, G), Std_LinkSelectLinkedFinal (S, D), Std_TreeViewActions (S, B / S, F) |
| T | Assembly_CreateJointGearBelt, Assembly_CreateJointGears; Draft_Text (T, E), Draft_Trimex (T, R); Sketcher_ConstrainTangent; Std_DockOverlayMouseTransparent (T, T); Std_TreeViewActions (T, 1-5 / T, D / T, G) |
| W | Assembly_CreateJointScrew; Draft_SelectPlane (W, P); Sketcher_Translate |
| X | Assembly_CreateJointAngle; Part_SelectFilter (X, S) |
| Z | Assembly_SolveAssembly; Sketcher's Z chords (Z, A / Z, E / Z, F / Z, H / Z, I / Z, K / Z, O / Z, P … / Z, R / Z, S / Z, T / Z, V / Z, Z) |
| Ctrl+B, Ctrl+I, Ctrl+U, Ctrl+Shift+A | Spreadsheet_StyleBold, StyleItalic, StyleUnderline, SetAlias |
| Ctrl+C, Ctrl+V, Ctrl+X | Sketcher_CopyClipboard, Sketcher_Paste, Sketcher_Cut |
| Ctrl+E, Ctrl+Shift+I | Std_Export, Std_Import |
| Home, End, F5, Alt+Return | Std_ViewHome, Std_RecallWorkingView, Std_Refresh, Std_Properties |

The ten keyboard access keys take none.

FreeCAD's own shortcuts that don't clash with these keep working, even though FreeCAD's menus and toolbars are hidden: NXStyle attaches every action that has a key to the main window, because Qt ignores a shortcut whose action sits only in hidden widgets.
