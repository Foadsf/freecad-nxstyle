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
| Move Object | <kbd>Ctrl</kbd>+<kbd>T</kbd> | `Std_TransformManip` | anywhere |  |
| Profile | <kbd>Z</kbd> | `Sketcher_CreatePolyline` | sketch |  |
| Rectangle | <kbd>R</kbd> | `Sketcher_CreateRectangle` | sketch |  |
| Line | <kbd>L</kbd> | `Sketcher_CreateLine` | sketch |  |
| Arc | <kbd>A</kbd> | `Sketcher_CreateArc` | sketch |  |
| Circle | <kbd>O</kbd> | `Sketcher_CreateCircle` | sketch |  |
| Polygon | <kbd>P</kbd> | `Sketcher_CreateRegularPolygon` | sketch |  |
| Studio Spline | <kbd>S</kbd> | `Sketcher_CreateBSpline` | sketch |  |
| Quick Trim | <kbd>T</kbd> | `Sketcher_Trimming` | sketch |  |
| Quick Extend | <kbd>E</kbd> | `Sketcher_Extend` | sketch |  |
| Fillet | <kbd>F</kbd> | `Sketcher_CreateFillet` | sketch |  |
| Rapid Dimension | <kbd>D</kbd> | `Sketcher_Dimension` | sketch |  |
| Geometric Constraints | <kbd>C</kbd> | `Sketcher_ConstrainCoincidentUnified` | sketch | FreeCAD applies one constraint per tool; C starts Coincident |
| Finish Sketch | <kbd>Ctrl</kbd>+<kbd>Q</kbd> | `Sketcher_LeaveSketch` | sketch |  |
| Hide | <kbd>Ctrl</kbd>+<kbd>B</kbd> | `Std_HideSelection` | anywhere |  |
| Show and Hide Panel | <kbd>Ctrl</kbd>+<kbd>W</kbd> | `NXStyle_ShowHide` | anywhere |  |
| Immediate Hide | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>I</kbd> | `NXStyle_ImmediateHide` | anywhere | pick objects to hide them; Esc to finish |
| Show Panel | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>K</kbd> | `Std_ShowSelection` | anywhere | select the hidden objects in the Part Navigator first |
| Show All | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>U</kbd> | `Std_ShowObjects` | anywhere |  |
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

FreeCAD's own shortcuts that don't clash with these keep working, even though FreeCAD's menus and toolbars are hidden: NXStyle attaches every action that has a key to the main window, because Qt ignores a shortcut whose action sits only in hidden widgets.
