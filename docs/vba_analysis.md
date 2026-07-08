# VBA-Analyse

- Generiert am: `2026-07-08T15:24:17.898219+00:00`
- Erkannte VBA-Module: `41`

## VBA/Tabelle1

- Zeilen: `393`
- Enthält Worksheet-Events
- Enthält CommandButton-/Form-Steuerungslogik
- Prozeduren: `Private Sub CommandButton1_Click(); Private Sub CommandButton2_Click(); Private Sub Worksheet_Activate(); Private Sub ScrollBar1_Change(); Private Sub Worksheet_BeforeDoubleClick(ByVal Target As Range, Cancel As Boolean); Sub UpdateScrollBar(); Sub UpdateRecipeList(); Sub NeuesRezeptHinzufügen(); Sub EinkaufslisteErstellen(); Sub BubbleSort(arr As Variant)`

```vb
Attribute VB_Name = "Tabelle1"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 3, 0, MSForms, CommandButton"
Attribute VB_Control = "ScrollBar1, 10, 1, MSForms, ScrollBar"
Attribute VB_Control = "CommandButton2, 11, 2, MSForms, CommandButton"
Private Sub CommandButton1_Click()
    Call NeuesRezeptHinzufügen
End Sub

Private Sub CommandButton2_Click()
    Call EinkaufslisteErstellen
End Sub

Private Sub Worksheet_Activate()
    ' Call UpdateScrollBar
    Call UpdateRecipeList
End Sub

Private Sub ScrollBar1_Change()
    Call UpdateRecipeList
End Sub

Private Sub Worksheet_BeforeDoubleClick(ByVal Target As Range, Cancel As Boolean)
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Sheets("Rezepte Übersicht")
    
    ' Bereich prüfen, ob Doppelklick in der Rezeptliste oder in der Checkbox-Spalte erfolgt ist
    If Not Intersect(Target, ws.Range("A11:A26")) Is Nothing Then
        ' Rezeptname aus der angeklickten Zelle erhalten
        Dim recipeName As String
        recipeName = Target.Value
        
        ' Zum entsprechenden Tabellenblatt wechseln
        On Error Resume Next
        Set ws = ThisWorkbook.Sheets(recipeName)
        On Error GoTo 0
        
        If Not ws Is Nothing Then
            ws.Activate
            Cancel = True ' Verhindert das Editieren der Zelle
        Else
            MsgBox "Rezeptblatt '" & recipeName & "' nicht gefunden.", vbExclamation
        End If
    ElseIf Not Intersect(Target, ws.Range("C11:C26")) Is Nothing Then
        ' Doppelklick auf die Checkbox-Spalte
        Dim displayedRecipeName As String
        displayedRecipeName = ws.Cells(Target.Row, 1).Value
        
        If SelectedRecipes.exists(displayedRecipeName) Then
            SelectedRecipes.Remove displayedRecipeName
            Target.Value = ""
        Else
            SelectedRecipes.Add displayedRecipeName, True
            Target.Value = ChrW(&H2713) ' Häkchen
        End If
        Cancel = True ' Verhindert das Editieren der Zelle
    End If
End Sub



Sub UpdateScrollBar()
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Sheets("Rezepte Übersicht")
    
    Dim recipeCount As Integer
    recipeCount = ThisWorkbook.Sheets.Count - 2 ' Annahme: Übersichtsblatt und Vorlagenblatt sind die ersten beiden Blätter
    
    If recipeCount > 16 Then
        ws.OLEObjects("ScrollBar1").Object.Max = recipeCount - 16
        ws.OLEObjects("ScrollBar1").Object.Enabled = True
    Else
        ws.OLEObjects("ScrollBar1").Object.Max = 1
        ws.OLEObjects("ScrollBar1").Object.Value = 1
        ws.OLEObjects("ScrollBar1").Object.Enabled = False
    End If
    ws.OLEObjects("ScrollBar1").Object.Min = 1
    ws.OLEObjects("ScrollBar1").Object.SmallChange = 1
    ws.OLEObjects("ScrollBar1").Object.LargeChange = 1
End Sub

Sub UpdateRecipeList()
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Sheets("Rezepte Übersicht")
    
    Dim i As Integer
    Dim startRow As Integer
    Dim endRow As Integer
    Dim firstRecipeIndex As Integer
    Dim lastRecipeIndex As Integer
    Dim recipeCount As Integer
    Dim recipeName As String
    Dim recipeWs As Worksheet
    
    startRow = 11 ' Erste Zelle der Rezeptliste
    endRow = 26 ' Letzte Zelle der Rezeptliste
    
    ' Leeren der Zellen
    ws.Range(ws.Cells(startRow, 1), ws.Cells(endRow, 1)).ClearContents
    ws.Range(ws.Cells(startRow, 2), ws.Cells(endRow, 2)).Interior.ColorIndex = 0 ' Entfernt die Färbung
    ws.Range(ws.Cells(startRow, 3), ws.Cells(endRow, 3)).ClearContents ' Entfernt die Häkchen
    
    ' Standardfarbe für leere Zellen in Spalte B
    Dim emptyCellColor As Long
    emptyCellColor = RGB(247, 199, 172)
    
    ' Setze die Standardfarbe für leere Zellen
    ws.Range(ws.Cells(startRow, 2), ws.Cells(endRow, 2)).Interior.Color = emptyCellColor
    
    recipeCount = ThisWorkbook.Sheets.Count - 2 ' Annahme: Übersichtsblatt und Vorlagenblatt sind die ersten beiden Blätter
    
    If recipeCount > 0 Then
        firstRecipeIndex = ws.OLEObjects("ScrollBar1").Object.Value
        lastRecipeIndex = Application.WorksheetFunction.Min(firstRecipeIndex + 15, recipeCount)
        
        For i = firstRecipeIndex To lastRecipeIndex
            recipeName = ThisWorkbook.Sheets(i + 2).Name
            ws.Cells(startRow + i - firstRecipeIndex, 1).Value = recipeName
            
            ' Überprüfen, ob das Rezept vegetarisch ist oder nicht
            Set recipeWs = ThisWorkbook.Sheets(recipeName)
            If recipeWs.Tab.Color = RGB(0, 255, 0) Then ' Grün für vegetarisch
                ws.Cells(startRow + i - firstRecipeIndex, 2).Interior.Color = RGB(0, 255, 0)
            ElseIf recipeWs.Tab.Color = RGB(255, 0, 0) Then ' Rot für nicht vegetarisch
                ws.Cells(startRow + i - firstRecipeIndex, 2).Interior.Color = RGB(255, 0, 0)
            Else
                ws.Cells(startRow + i - firstRecipeIndex, 2).Interior.ColorIndex = 0 ' Keine Farbe
            End If
            
            ' Überprüfen, ob das Rezept ausgewählt ist
            If SelectedRecipes.exists(recipeName) Then
                ws.Cells(startRow + i - firstRecipeIndex, 3).Value = ChrW(&H2713) ' Häkchen
            End If
        Next i
    End If
End Sub





Sub NeuesRezeptHinzufügen()
    Dim rezeptName As String
    Dim antwort As VbMsgBoxResult
    Dim IstVegetarisch As Boolean
    Dim newWs As Worksheet
    Dim VorlageWs As Worksheet
    Dim newSheetName As String
    Dim newSheetColor As Long

    ' Vorlage Tabellenblatt definieren
    Set VorlageWs = ThisWorkbook.Sheets("Vorlage")
    
    ' Schritt 1: Nach dem Namen des Rezepts fragen
    rezeptName = InputBox("Bitte geben Sie den Namen des Rezepts ein:", "Neues Rezept")
    
    ' Schritt 2: Prüfen, ob der Name gültig ist
    If rezeptName = "" Then
        MsgBox "Kein gültiger Name eingegeben. Vorgang abgebrochen.", vbExclamation
        Exit Sub
    End If
    
    ' Schritt 3: Abfragen, ob das Rezept vegetarisch ist
    antwort = MsgBox("Ist das Rezept vegetarisch?", vbYesNo + vbQuestion, "Vegetarisch?")
    IstVegetarisch = (antwort = vbYes)
    
    ' Schritt 4: Neues Tabellenblatt erstellen und benennen
    Set newWs = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
    newWs.Name = rezeptName
    
    ' Schritt 5: Vorlage kopieren
    VorlageWs.Cells.Copy Destination:=newWs.Cells
    
    ' Schritt 6: Rezeptname in Zelle E2 eintragen
    With newWs.Range("E2")
        .Value = rezeptName
        .Font.Size = 22
    End With
    
    ' Schritt 7: Tabellenblattreiter einfärben
    If IstVegetarisch Then
        newSheetColor = RGB(0, 255, 0) ' Grün für vegetarisch
    Else
        newSheetColor = RGB(255, 0, 0) ' Rot für Fleischgerichte
    End If
    newWs.Tab.Color = newSheetColor
    
   
End Sub
Sub EinkaufslisteErstellen()
    Dim wsÜbersicht As Worksheet
    Dim wsEinkaufsliste As Worksheet
    Dim wsRezept As Worksheet
    Dim lastRow As Long
    Dim rezeptName As Variant
    Dim rezeptRow As Long
    Dim zutat As String
    Dim menge As Double
    Dim einheit As String
    Dim preis As Double
    Dim targetRow As Long
    Dim dict As Object
    Dim key As Variant
    Dim rezeptInfo As String
    Dim portionen As Long
    Dim rezeptDict As Object
    Dim gesamtKostenRow As Long
    Dim keys As Variant
    Dim i As Long
    Dim fehlendeZutaten As String
    Dim unterschiedlichePreise As String
    
    ' Setze das Dictionary für die Zutatenliste
    Set dict = CreateObject("Scripting.Dictionary")
    Set rezeptDict = CreateObject("Scripting.Dictionary")
    
    ' Setze das Übersichtstabellenblatt
    Set wsÜbersicht = ThisWorkbook.Sheets("Rezepte Übersicht")
    
    ' Schleife durch das SelectedRecipes Dictionary und überprüfe die ausgewählten Rezepte
    For Each rezeptName In SelectedRecipes.keys
        ' Setze das Rezepttabellenblatt
        Set wsRezept = ThisWorkbook.Sheets(rezeptName)
        
        ' Hole die Anzahl der Portionen
        portionen = wsRezept.Cells(6, 8).Value
        
        ' Schleife durch die Zutatenliste im Rezepttabellenblatt
        rezeptRow = 9 ' Annahme: Die Zutatenliste beginnt in Zeile 9
        Do While wsRezept.Cells(rezeptRow, 1).Value <> "Gesamtkosten:"
            If wsRezept.Cells(rezeptRow, 1).Value <> "" Then
                zutat = wsRezept.Cells(rezeptRow, 1).Value
                menge = wsRezept.Cells(rezeptRow, 4).Value
                einheit = wsRezept.Cells(rezeptRow, 3).Value
                preis = wsRezept.Cells(rezeptRow, 5).Value
                
                ' Hinzufügen oder Aktualisieren der Zutat im Dictionary
                If dict.exists(zutat) Then
                    If dict(zutat)(2) <> preis Then
                        If preis > dict(zutat)(2) Then
                            ' Aktualisieren der bisherigen Einträge mit dem höheren Preis
                            'UpdatePricesInRecipeSheets zutat, preis
                            dict(zutat) = Array(dict(zutat)(0) + menge, einheit, preis, dict(zutat)(3) & ", " & rezeptName)
                        Else
                            ' Preis im aktuellen Tabellenblatt aktualisieren
                            wsRezept.Cells(rezeptRow, 5).Value = dict(zutat)(2)
                        End If
                        unterschiedlichePreise = unterschiedlichePreise & zutat & " in " & rezeptName & " hat einen anderen Preis als in vorherigen Rezepten." & vbCrLf
                    Else
                        dict(zutat) = Array(dict(zutat)(0) + menge, einheit, preis, dict(zutat)(3) & ", " & rezeptName)
                    End If
                Else
                    dict.Add zutat, Array(menge, einheit, preis, rezeptName)
                End If
            End If
            rezeptRow = rezeptRow + 1
        Loop
        
        ' Preis pro Portion und Gesamtpreis ermitteln
        gesamtPreis = wsRezept.Cells(rezeptRow, 6).Value
        preisProPortion = wsRezept.Cells(rezeptRow, 8).Value
        
        ' Speichern der Rezeptinformationen im Dictionary
        rezeptDict.Add rezeptName, Array(portionen, preisProPortion, gesamtPreis)
    Next rezeptName
    
    ' Neues Tabellenblatt für die Einkaufsliste erstellen
    On Error Resume Next
    Set wsEinkaufsliste = ThisWorkbook.Sheets("Einkaufsliste")
    On Error GoTo 0
    If Not wsEinkaufsliste Is Nothing Then
        Application.DisplayAlerts = False
        wsEinkaufsliste.Delete
        Application.DisplayAlerts = True
    End If
    Set wsEinkaufsliste = ThisWorkbook.Sheets.Add
    wsEinkaufsliste.Name = "Einkaufsliste"
    
    ' Überschriften für die Einkaufsliste
    wsEinkaufsliste.Cells(1, 1).Value = "Zutat"
    wsEinkaufsliste.Cells(1, 2).Value = "Menge"
    wsEinkaufsliste.Cells(1, 3).Value = "Einheit"
    wsEinkaufsliste.Cells(1, 4).Value = "Preis pro Einheit"
    wsEinkaufsliste.Cells(1, 5).Value = "Gesamtpreis"
    wsEinkaufsliste.Cells(1, 6).Value = "Gerichte"
    
    ' Alphabetisch sortierte Schlüssel des Dictionaries
    keys = dict.keys
    Call BubbleSort(keys)
    
    ' Hinzufügen der gesammelten Zutaten zur Einkaufsliste
    targetRow = 2
    For i = LBound(keys) To UBound(keys)
        key = keys(i)
        wsEinkaufsliste.Cells(targetRow, 1).Value = key
        wsEinkaufsliste.Cells(targetRow, 2).Value = dict(key)(0)
        wsEinkaufsliste.Cells(targetRow, 3).Value = dict(key)(1)
        wsEinkaufsliste.Cells(targetRow, 4).Value = dict(key)(2)
        wsEinkaufsliste.Cells(targetRow, 5).Formula = "=" & wsEinkaufsliste.Cells(targetRow, 2).Address & "*" & wsEinkaufsliste.Cells(targetRow, 4).Address
        wsEinkaufsliste.Cells(targetRow, 6).Value = dict(key)(3)
        targetRow = targetRow + 1
    Next i
    
    ' Gesamtkosten berechnen
    gesamtKostenRow = targetRow + 1
    wsEinkaufsliste.Cells(gesamtKostenRow, 4).Value = "Gesamtkosten:"
    wsEinkaufsliste.Cells(gesamtKostenRow, 5).Formula = "=SUM(E2:E" & targetRow - 1 & ")"
    
    ' Hinzufügen der Rezeptinformationen
    targetRow = gesamtKostenRow + 2
    wsEinkaufsliste.Cells(targetRow, 1).Value = "Gerichte:"
    targetRow = targetRow + 1
    For Each key In rezeptDict.keys
        wsEinkaufsliste.Cells(targetRow, 1).Value = key
        wsEinkaufsliste.Cells(targetRow, 2).Value = rezeptDict(key)(0)
        wsEinkaufsliste.Cells(targetRow, 3).Value = "Portionen"
        wsEinkaufsliste.Cells(targetRow, 4).Value = rezeptDict(key)(1)
        wsEinkaufsliste.Cells(targetRow, 5).Value = rezeptDict(key)(2)
        targetRow = targetRow + 1
    Next key
    
    ' Überprüfung der Vollständigkeit der Zutaten
    fehlendeZutaten = ""
    For Each rezeptName In SelectedRecipes.keys
        Set wsRezept = ThisWorkbook.Sheets(rezeptName)
        rezeptRow = 9
        Do While wsRezept.Cells(rezeptRow, 1).Value <> "Gesamtkosten:"
            If wsRezept.Cells(rezeptRow, 1).Value <> "" Then
                zutat = wsRezept.Cells(rezeptRow, 1).Value
                If Not dict.exists(zutat) Then
                    fehlendeZutaten = fehlendeZutaten & zutat & " im Rezept " & rezeptName & vbCrLf
                End If
            End If
            rezeptRow = rezeptRow + 1
        Loop
    Next rezeptName
    
    If fehlendeZutaten <> "" Then
        MsgBox "Die folgenden Zutaten fehlen in der Einkaufsliste: " & vbCrLf & fehlendeZutaten, vbExclamation
    End If
    
    If unterschiedlichePreise <> "" Then
        MsgBox "Die folgenden Zutaten hatten unterschiedliche Preise, der höchste Preis wurde übernommen und in allen Rezepten angepasst: " & vbCrLf & unterschiedlichePreise, vbInformation
    Else
        MsgBox "Alle Zutaten wurden erfolgreich in die Einkaufsliste aufgenommen.", vbInformation
    End If
    
    ' Formatieren der Einkaufsliste für den Ausdruck auf DIN A4
    With wsEinkaufsliste.PageSetup
        .Orientation = xlPortrait
        .PaperSize = xlPaperA4
        .FitToPagesWide = 1
        .FitToPagesTall = False
        .Zoom = False
        .PrintGridlines = True
    End With
    
    ' Autofit für Spalten
    wsEinkaufsliste.Columns("A:F").AutoFit
    
    ' Kopfzeile und Fußzeile einstellen
    With wsEinkaufsliste.PageSetup
        .CenterHeader = "Einkaufsliste"
        .CenterFooter = "Seite &P von &N"
        .LeftFooter = "&D"
        .RightFooter = "&T"
    End With
End Sub


Sub BubbleSort(arr As Variant)
    Dim i As Long, j As Long
    Dim temp As Variant
    For i = LBound(arr) To UBound(arr) - 1
        For j = i + 1 To UBound(arr)
            If arr(i) > arr(j) Then
                temp = arr(i)
                arr(i) = arr(j)
                arr(j) = temp
            End If
        Next j
    Next i
End Sub
```

## VBA/DieseArbeitsmappe

- Zeilen: `52`
- Enthält Workbook-Events
- Prozeduren: `Private Sub Workbook_Open(); Private Sub Workbook_SheetChange(ByVal Sh As Object, ByVal Target As Range)`

```vb
Attribute VB_Name = "DieseArbeitsmappe"
Attribute VB_Base = "0{00020819-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Private Sub Workbook_Open()
    Call InitializeSelectedRecipes
End Sub

Private Sub Workbook_SheetChange(ByVal Sh As Object, ByVal Target As Range)
    Dim wsPreisliste As Worksheet
    Dim rezeptRow As Long
    Dim zutat As String
    Dim preis As Double
    Dim foundCell As Range
    
    ' Prüfen, ob die Änderung in einem Rezepttabellenblatt erfolgt ist
    If Sh.Name <> "Rezepte Übersicht" And Sh.Name <> "Einkaufsliste" And Sh.Name <> "Vorlage" And Sh.Name <> "Preisliste" Then
        ' Prüfen, ob die Änderung in der Spalte der Zutaten oder Preise erfolgt ist
        If Not Intersect(Target, Sh.Columns(1)) Is Nothing Or Not Intersect(Target, Sh.Columns(5)) Is Nothing Then
            Application.EnableEvents = False ' Verhindert Rekursion
            Set wsPreisliste = ThisWorkbook.Sheets("Preisliste")
            
            ' Aktualisieren der Preisliste
            rezeptRow = 9 ' Annahme: Die Zutatenliste beginnt in Zeile 9
            Do While Sh.Cells(rezeptRow, 1).Value <> "Gesamtkosten:"
                If Sh.Cells(rezeptRow, 1).Value <> "" Then
                    zutat = Sh.Cells(rezeptRow, 1).Value
                    preis = Sh.Cells(rezeptRow, 5).Value
                    
                    ' Prüfen, ob die Zutat bereits in der Preisliste vorhanden ist
                    Set foundCell = wsPreisliste.Columns(1).Find(zutat, LookIn:=xlValues, LookAt:=xlWhole)
                    If Not foundCell Is Nothing Then
                        ' Preis in der Preisliste aktualisieren
                        ' wsPreisliste.Cells(foundCell.Row, 2).Value = preis
                    Else
                        ' Neue Zutat zur Preisliste hinzufügen
                        wsPreisliste.Cells(wsPreisliste.Rows.Count, 1).End(xlUp).Offset(1, 0).Value = zutat
                        wsPreisliste.Cells(wsPreisliste.Rows.Count, 1).End(xlUp).Offset(0, 1).Value = preis
                    End If
                End If
                rezeptRow = rezeptRow + 1
            Loop
            
            Application.EnableEvents = True
        End If
    End If
End Sub
```

## VBA/Tabelle2

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle2"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle3

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle3"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle4

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle4"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle5

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle5"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle6

- Zeilen: `12`
- Enthält CommandButton-/Form-Steuerungslogik
- Prozeduren: `Private Sub CommandButton1_Click()`

```vb
Attribute VB_Name = "Tabelle6"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 1, 0, MSForms, CommandButton"
Private Sub CommandButton1_Click()
    PreiseAutomatischEintragenAktuellesBlatt
End Sub
```

## VBA/Tabelle7

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle7"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle8

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle8"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle9

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle9"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle10

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle10"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle11

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle11"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle12

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle12"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle34

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle34"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle14

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle14"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle15

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle15"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle16

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle16"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle17

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle17"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Modul1

- Zeilen: `6`
- Prozeduren: `Sub InitializeSelectedRecipes()`

```vb
Attribute VB_Name = "Modul1"
Public SelectedRecipes As Object

Sub InitializeSelectedRecipes()
    Set SelectedRecipes = CreateObject("Scripting.Dictionary")
End Sub
```

## VBA/Tabelle18

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle18"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle19

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle19"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle20

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle20"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle21

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle21"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle22

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle22"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle23

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle23"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle31

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle31"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle30

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle30"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle35

- Zeilen: `38`
- Enthält Worksheet-Events
- Prozeduren: `Private Sub Worksheet_Change(ByVal Target As Range)`

```vb
Attribute VB_Name = "Tabelle35"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Private Sub Worksheet_Change(ByVal Target As Range)
    Dim ws As Worksheet
    Dim rezeptRow As Long
    Dim zutat As String
    Dim neuerPreis As Double
    
    ' Prüfen, ob die Änderung in der Preisliste erfolgt ist
    If Target.Column = 2 Then
        Application.EnableEvents = False ' Verhindert Rekursion
        zutat = Target.Offset(0, -1).Value
        neuerPreis = Target.Value
        
        ' Schleife durch alle Arbeitsblätter und aktualisiere den Preis
        For Each ws In ThisWorkbook.Worksheets
            If ws.Name <> "Rezepte Übersicht" And ws.Name <> "Einkaufsliste" And ws.Name <> "Vorlage" And ws.Name <> "Preisliste" Then
                rezeptRow = 9 ' Annahme: Die Zutatenliste beginnt in Zeile 9
                Do While ws.Cells(rezeptRow, 1).Value <> "Gesamtkosten:"
                    If ws.Cells(rezeptRow, 1).Value <> "" Then
                        If ws.Cells(rezeptRow, 1).Value = zutat Then
                            ws.Cells(rezeptRow, 5).Value = neuerPreis
                        End If
                    End If
                    rezeptRow = rezeptRow + 1
                Loop
            End If
        Next ws
        Application.EnableEvents = True
    End If
End Sub
```

## VBA/Modul2

- Zeilen: `59`
- Prozeduren: `Sub ErstellePreisliste()`

```vb
Attribute VB_Name = "Modul2"
Sub ErstellePreisliste()
    Dim wsPreisliste As Worksheet
    Dim wsRezept As Worksheet
    Dim rezeptRow As Long
    Dim zutat As String
    Dim preis As Double
    Dim dict As Object
    Dim key As Variant
    Dim i As Long
    
    ' Setze das Dictionary für die Zutatenliste
    Set dict = CreateObject("Scripting.Dictionary")
    
    ' Schleife durch alle Arbeitsblätter und erfasse die Zutaten und Preise
    For Each wsRezept In ThisWorkbook.Worksheets
        If wsRezept.Name <> "Rezepte Übersicht" And wsRezept.Name <> "Einkaufsliste" And wsRezept.Name <> "Vorlage" And wsRezept.Name <> "Preisliste" Then
            rezeptRow = 9 ' Annahme: Die Zutatenliste beginnt in Zeile 9
            Do While wsRezept.Cells(rezeptRow, 1).Value <> "Gesamtkosten:" And wsRezept.Cells(rezeptRow, 1).Value <> ""
                zutat = wsRezept.Cells(rezeptRow, 1).Value
                preis = wsRezept.Cells(rezeptRow, 5).Value
                
                ' Hinzufügen oder Aktualisieren der Zutat im Dictionary
                If Not dict.exists(zutat) Then
                    dict.Add zutat, preis
                End If
                rezeptRow = rezeptRow + 1
            Loop
        End If
    Next wsRezept
    
    ' Neues Tabellenblatt für die Preisliste erstellen
    On Error Resume Next
    Set wsPreisliste = ThisWorkbook.Sheets("Preisliste")
    On Error GoTo 0
    If Not wsPreisliste Is Nothing Then
        Application.DisplayAlerts = False
        wsPreisliste.Delete
        Application.DisplayAlerts = True
    End If
    Set wsPreisliste = ThisWorkbook.Sheets.Add
    wsPreisliste.Name = "Preisliste"
    
    ' Überschriften für die Preisliste
    wsPreisliste.Cells(1, 1).Value = "Zutat"
    wsPreisliste.Cells(1, 2).Value = "Preis"
    
    ' Hinzufügen der gesammelten Zutaten und Preise zur Preisliste
    i = 2
    For Each key In dict.keys
        wsPreisliste.Cells(i, 1).Value = key
        wsPreisliste.Cells(i, 2).Value = dict(key)
        i = i + 1
    Next key
    
    ' Autofit für Spalten
    wsPreisliste.Columns("A:B").AutoFit
End Sub
```

## VBA/Modul3

- Zeilen: `92`
- Prozeduren: `Sub PreiseAusPreislisteInZielblattEintragen()`

```vb
Attribute VB_Name = "Modul3"
Sub PreiseAusPreislisteInZielblattEintragen()
    Dim wsPl      As Worksheet
    Dim wsAk      As Worksheet
    Dim sheetName As String
    Dim lastRow   As Long
    Dim i         As Long
    Dim zutat     As String
    Dim foundCell As Range
    Dim price     As Variant
    Dim unit      As String
    Dim suggestions As Collection
    Dim key       As Variant
    Dim s As String
    Dim choice    As String
    Dim idx       As Long
    Dim newName   As String
    Dim insertRow As Long

    Set wsPl = ThisWorkbook.Worksheets("Preisliste")
    sheetName = ActiveSheet.Name
    If sheetName = wsPl.Name Then
        MsgBox "Bitte aktiviere zuerst dein Rezeptblatt, dann führe das Makro aus.", vbExclamation
        Exit Sub
    End If
    If MsgBox("Preise aus 'Preisliste' in Blatt '" & sheetName & "' übertragen?", _
              vbOKCancel + vbQuestion, "Zielblatt bestätigen") <> vbOK Then Exit Sub
    Set wsAk = ThisWorkbook.Worksheets(sheetName)
    lastRow = wsAk.Cells(wsAk.Rows.Count, 1).End(xlUp).Row

    Application.ScreenUpdating = False
    Application.EnableEvents = False

    For i = 9 To lastRow
        zutat = Trim(wsAk.Cells(i, 1).Value)
        If zutat = "" Or zutat = "Gesamtkosten:" Then Exit For
        Set foundCell = wsPl.Columns(1).Find(What:=zutat, LookIn:=xlValues, _
                                            LookAt:=xlWhole, MatchCase:=False)
        If Not foundCell Is Nothing Then
            price = wsPl.Cells(foundCell.Row, 2).Value
            If IsNumeric(price) And price > 0 Then
                wsAk.Cells(i, 5).Value = price
                wsAk.Cells(i, 6).Value = wsPl.Cells(foundCell.Row, 3).Value
            End If
        Else
            ' Ähnliche Zutaten sammeln
            Set suggestions = New Collection
            For Each key In wsPl.Range("A2", wsPl.Cells(wsPl.Rows.Count, 1).End(xlUp))
                If InStr(1, LCase(key.Value), LCase(zutat), vbTextCompare) > 0 Then
                    suggestions.Add key.Value
                End If
            Next key
            ' Vorschläge zusammenbauen
            s = "Zutat '" & zutat & "' nicht gefunden." & vbCrLf & _
                "Gefundene Ähnlichkeiten:" & vbCrLf
            For idx = 1 To suggestions.Count
                s = s & idx & ". " & suggestions(idx) & vbCrLf
            Next
            s = s & vbCrLf & "Bitte Nummer wählen oder neuen Namen eingeben:"
            choice = InputBox(s, "Ähnliche Zutaten")
            If choice = "" Then
                MsgBox "Überspringe Zutat " & zutat, vbExclamation
            ElseIf IsNumeric(choice) And _
                   CLng(choice) >= 1 And CLng(choice) <= suggestions.Count Then
                newName = suggestions(CLng(choice))
            Else
                newName = choice
                ' Einheit und Preis für neuen Eintrag abfragen
                unit = InputBox("Einheit für '" & newName & "' eingeben:", "Neue Einheit")
                price = InputBox("Preis für '" & newName & "' eingeben:", "Neuer Preis")
                ' In Preisliste eintragen
                insertRow = wsPl.Cells(wsPl.Rows.Count, 1).End(xlUp).Row + 1
                wsPl.Cells(insertRow, 1).Value = newName
                wsPl.Cells(insertRow, 2).Value = price
                wsPl.Cells(insertRow, 3).Value = unit
            End If
            ' Rezeptblatt anpassen und Preis/Einheit einfügen
            wsAk.Cells(i, 1).Value = newName
            If IsNumeric(price) And price > 0 Then
                wsAk.Cells(i, 5).Value = price
                wsAk.Cells(i, 6).Value = unit
            End If
        End If
    Next i

    Application.EnableEvents = True
    Application.ScreenUpdating = True

    MsgBox "Preise und Einheiten wurden in '" & wsAk.Name & "' eingetragen.", vbInformation
End Sub
```

## VBA/Tabelle24

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle24"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle25

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle25"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle26

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle26"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle27

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle27"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle29

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle29"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle32

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle32"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle33

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle33"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle13

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle13"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle28

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle28"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle36

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle36"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```

## VBA/Tabelle37

- Zeilen: `8`

```vb
Attribute VB_Name = "Tabelle37"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
```
