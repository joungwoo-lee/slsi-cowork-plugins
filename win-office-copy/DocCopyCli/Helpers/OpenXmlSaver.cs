using System.Text;
using ClosedXML.Excel;
using DocCopyCli.Models;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;
using A = DocumentFormat.OpenXml.Drawing;
using P = DocumentFormat.OpenXml.Presentation;

namespace DocCopyCli.Helpers;

internal static class OpenXmlSaver
{
    public static string NormalizeWordOutputPath(string outputPath)
        => Path.ChangeExtension(outputPath, ".docx");

    public static string NormalizeExcelOutputPath(string outputPath)
        => Path.ChangeExtension(outputPath, ".xlsx");

    public static string NormalizePowerPointOutputPath(string outputPath)
        => Path.ChangeExtension(outputPath, ".pptx");

    public static void SaveWordDocument(string outputPath, string textContent)
    {
        EnsureDirectory(outputPath);

        using var document = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);
        var mainPart = document.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        var normalized = SanitizeXmlText(textContent).Replace("\r\n", "\n").Replace('\r', '\n');
        foreach (string paragraphText in normalized.Split('\n'))
        {
            body.AppendChild(new Paragraph(new Run(new Text(paragraphText) { Space = SpaceProcessingModeValues.Preserve })));
        }

        mainPart.Document.Save();
        Console.Error.WriteLine($"[OpenXmlSaver] Saved Word document: {outputPath}");
    }

    public static void SaveWorkbook(string outputPath, IReadOnlyList<ExcelSheetSnapshot> sheets)
    {
        EnsureDirectory(outputPath);

        using var workbook = new XLWorkbook();
        bool addedSheet = false;

        foreach (var sheet in sheets)
        {
            string name = SanitizeSheetName(sheet.Name, workbook.Worksheets.Select(ws => ws.Name).ToHashSet(StringComparer.OrdinalIgnoreCase));
            var ws = workbook.Worksheets.Add(name);
            addedSheet = true;

            for (int rowIndex = 0; rowIndex < sheet.Rows.Count; rowIndex++)
            {
                var row = sheet.Rows[rowIndex];
                for (int colIndex = 0; colIndex < row.Count; colIndex++)
                {
                    ws.Cell(rowIndex + 1, colIndex + 1).Value = row[colIndex];
                }
            }

            if (sheet.Rows.Count > 0)
            {
                ws.Columns().AdjustToContents();
            }
        }

        if (!addedSheet)
        {
            workbook.Worksheets.Add("Sheet1");
        }

        workbook.SaveAs(outputPath);
        Console.Error.WriteLine($"[OpenXmlSaver] Saved Excel workbook: {outputPath}");
    }

    public static void SavePresentation(string outputPath, IReadOnlyList<string> slides)
    {
        EnsureDirectory(outputPath);

        using var presentationDocument = PresentationDocument.Create(outputPath, PresentationDocumentType.Presentation);
        var presentationPart = presentationDocument.AddPresentationPart();
        presentationPart.Presentation = new P.Presentation();

        var slideMasterPart = presentationPart.AddNewPart<SlideMasterPart>();
        var slideLayoutPart = slideMasterPart.AddNewPart<SlideLayoutPart>();
        var themePart = slideMasterPart.AddNewPart<ThemePart>();

        GenerateThemePart(themePart);
        GenerateSlideLayoutPart(slideLayoutPart);
        GenerateSlideMasterPart(slideMasterPart, slideLayoutPart, themePart);

        var slideIdList = new P.SlideIdList();
        uint slideId = 256U;

        if (slides.Count == 0)
        {
            var slidePart = presentationPart.AddNewPart<SlidePart>();
            slidePart.AddPart(slideLayoutPart);
            GenerateSlidePart(slidePart, string.Empty);
            slideIdList.Append(new P.SlideId
            {
                Id = slideId++,
                RelationshipId = presentationPart.GetIdOfPart(slidePart),
            });
        }
        else
        {
            foreach (string slideText in slides)
            {
                var slidePart = presentationPart.AddNewPart<SlidePart>();
                slidePart.AddPart(slideLayoutPart);
                GenerateSlidePart(slidePart, slideText);
                slideIdList.Append(new P.SlideId
                {
                    Id = slideId++,
                    RelationshipId = presentationPart.GetIdOfPart(slidePart),
                });
            }
        }

        presentationPart.Presentation.Append(new P.SlideMasterIdList(
            new P.SlideMasterId
            {
                Id = 2147483648U,
                RelationshipId = presentationPart.GetIdOfPart(slideMasterPart),
            }));
        presentationPart.Presentation.Append(slideIdList);
        presentationPart.Presentation.SlideSize = new P.SlideSize { Cx = 9144000, Cy = 5143500 };
        presentationPart.Presentation.NotesSize = new P.NotesSize { Cx = 6858000, Cy = 9144000 };
        presentationPart.Presentation.Save();

        Console.Error.WriteLine($"[OpenXmlSaver] Saved PowerPoint presentation: {outputPath}");
    }

    private static string SanitizeSheetName(string? name, HashSet<string> existingNames)
    {
        string cleaned = string.IsNullOrWhiteSpace(name) ? "Sheet" : name;
        foreach (char invalid in new[] { ':', '\\', '/', '?', '*', '[', ']' })
            cleaned = cleaned.Replace(invalid, '_');

        cleaned = cleaned.Trim();
        if (cleaned.Length == 0) cleaned = "Sheet";
        if (cleaned.Length > 31) cleaned = cleaned[..31];

        string candidate = cleaned;
        int suffix = 2;
        while (existingNames.Contains(candidate))
        {
            string tail = $"_{suffix++}";
            int maxBaseLength = Math.Max(1, 31 - tail.Length);
            candidate = cleaned[..Math.Min(cleaned.Length, maxBaseLength)] + tail;
        }

        existingNames.Add(candidate);
        return candidate;
    }

    private static void GenerateSlidePart(SlidePart slidePart, string slideText)
    {
        var shapeTree = new P.ShapeTree(
            new P.NonVisualGroupShapeProperties(
                new P.NonVisualDrawingProperties { Id = 1U, Name = string.Empty },
                new P.NonVisualGroupShapeDrawingProperties(),
                new P.ApplicationNonVisualDrawingProperties()),
            new P.GroupShapeProperties(
                new A.TransformGroup(
                    new A.Offset { X = 0L, Y = 0L },
                    new A.Extents { Cx = 0L, Cy = 0L },
                    new A.ChildOffset { X = 0L, Y = 0L },
                    new A.ChildExtents { Cx = 0L, Cy = 0L })),
            CreateSlideTextShape(slideText));

        slidePart.Slide = new P.Slide(
            new P.CommonSlideData(shapeTree),
            new P.ColorMapOverride(new A.MasterColorMapping()));
        slidePart.Slide.Save();
    }

    private static P.Shape CreateSlideTextShape(string slideText)
    {
        var paragraphs = BuildSlideParagraphs(slideText);
        if (paragraphs.Count == 0)
            paragraphs.Add(new A.Paragraph(new A.EndParagraphRunProperties { Language = "en-US", FontSize = 1800 }));

        return new P.Shape(
            new P.NonVisualShapeProperties(
                new P.NonVisualDrawingProperties { Id = 2U, Name = "Content Placeholder 1" },
                new P.NonVisualShapeDrawingProperties(new A.ShapeLocks { NoGrouping = true }),
                new P.ApplicationNonVisualDrawingProperties()),
            new P.ShapeProperties(
                new A.Transform2D(
                    new A.Offset { X = 457200L, Y = 457200L },
                    new A.Extents { Cx = 8229600L, Cy = 4114800L })),
            new P.TextBody(
                new A.BodyProperties { LeftInset = 0, RightInset = 0, TopInset = 0, BottomInset = 0, Wrap = A.TextWrappingValues.Square },
                new A.ListStyle(),
                paragraphs.ToArray()));
    }

    private static List<A.Paragraph> BuildSlideParagraphs(string slideText)
    {
        var paragraphs = new List<A.Paragraph>();
        string normalized = SanitizeXmlText(slideText).Replace("\r\n", "\n").Replace('\r', '\n');

        foreach (string line in normalized.Split('\n'))
        {
            var paragraph = new A.Paragraph();
            if (line.Length > 0)
            {
                paragraph.Append(new A.Run(
                    new A.RunProperties { Language = "en-US", FontSize = 1800, Dirty = false },
                    new A.Text(line)));
            }

            paragraph.Append(new A.EndParagraphRunProperties { Language = "en-US", FontSize = 1800, Dirty = false });
            paragraphs.Add(paragraph);
        }

        return paragraphs;
    }

    private static void GenerateSlideLayoutPart(SlideLayoutPart slideLayoutPart)
    {
        slideLayoutPart.SlideLayout = new P.SlideLayout(
            new P.CommonSlideData(
                new P.ShapeTree(
                    new P.NonVisualGroupShapeProperties(
                        new P.NonVisualDrawingProperties { Id = 1U, Name = string.Empty },
                        new P.NonVisualGroupShapeDrawingProperties(),
                        new P.ApplicationNonVisualDrawingProperties()),
                    new P.GroupShapeProperties(
                        new A.TransformGroup(
                            new A.Offset { X = 0L, Y = 0L },
                            new A.Extents { Cx = 0L, Cy = 0L },
                            new A.ChildOffset { X = 0L, Y = 0L },
                            new A.ChildExtents { Cx = 0L, Cy = 0L })))),
            new P.ColorMapOverride(new A.MasterColorMapping()));
        slideLayoutPart.SlideLayout.Type = P.SlideLayoutValues.Blank;
        slideLayoutPart.SlideLayout.Preserve = true;
        slideLayoutPart.SlideLayout.Save();
    }

    private static void GenerateSlideMasterPart(SlideMasterPart slideMasterPart, SlideLayoutPart slideLayoutPart, ThemePart themePart)
    {
        slideMasterPart.SlideMaster = new P.SlideMaster(
            new P.CommonSlideData(
                new P.ShapeTree(
                    new P.NonVisualGroupShapeProperties(
                        new P.NonVisualDrawingProperties { Id = 1U, Name = string.Empty },
                        new P.NonVisualGroupShapeDrawingProperties(),
                        new P.ApplicationNonVisualDrawingProperties()),
                    new P.GroupShapeProperties(
                        new A.TransformGroup(
                            new A.Offset { X = 0L, Y = 0L },
                            new A.Extents { Cx = 0L, Cy = 0L },
                            new A.ChildOffset { X = 0L, Y = 0L },
                            new A.ChildExtents { Cx = 0L, Cy = 0L })))),
            new P.ColorMap
            {
                Background1 = A.ColorSchemeIndexValues.Light1,
                Text1 = A.ColorSchemeIndexValues.Dark1,
                Background2 = A.ColorSchemeIndexValues.Light2,
                Text2 = A.ColorSchemeIndexValues.Dark2,
                Accent1 = A.ColorSchemeIndexValues.Accent1,
                Accent2 = A.ColorSchemeIndexValues.Accent2,
                Accent3 = A.ColorSchemeIndexValues.Accent3,
                Accent4 = A.ColorSchemeIndexValues.Accent4,
                Accent5 = A.ColorSchemeIndexValues.Accent5,
                Accent6 = A.ColorSchemeIndexValues.Accent6,
                Hyperlink = A.ColorSchemeIndexValues.Hyperlink,
                FollowedHyperlink = A.ColorSchemeIndexValues.FollowedHyperlink,
            },
            new P.SlideLayoutIdList(
                new P.SlideLayoutId
                {
                    Id = 2147483649U,
                    RelationshipId = slideMasterPart.GetIdOfPart(slideLayoutPart),
                }),
            new P.TextStyles(
                new P.TitleStyle(),
                new P.BodyStyle(),
                new P.OtherStyle()));

        slideMasterPart.SlideMaster.Save();
    }

    private static void GenerateThemePart(ThemePart themePart)
    {
        themePart.Theme = new A.Theme(
            new A.ThemeElements(
                new A.ColorScheme(
                    new A.Dark1Color(new A.SystemColor { Val = A.SystemColorValues.WindowText, LastColor = "000000" }),
                    new A.Light1Color(new A.SystemColor { Val = A.SystemColorValues.Window, LastColor = "FFFFFF" }),
                    new A.Dark2Color(new A.RgbColorModelHex { Val = "1F1F1F" }),
                    new A.Light2Color(new A.RgbColorModelHex { Val = "F3F3F3" }),
                    new A.Accent1Color(new A.RgbColorModelHex { Val = "4472C4" }),
                    new A.Accent2Color(new A.RgbColorModelHex { Val = "ED7D31" }),
                    new A.Accent3Color(new A.RgbColorModelHex { Val = "A5A5A5" }),
                    new A.Accent4Color(new A.RgbColorModelHex { Val = "FFC000" }),
                    new A.Accent5Color(new A.RgbColorModelHex { Val = "5B9BD5" }),
                    new A.Accent6Color(new A.RgbColorModelHex { Val = "70AD47" }),
                    new A.Hyperlink(new A.RgbColorModelHex { Val = "0563C1" }),
                    new A.FollowedHyperlinkColor(new A.RgbColorModelHex { Val = "954F72" }))
                { Name = "DocCopyCli Colors" },
                new A.FontScheme(
                    new A.MajorFont(
                        new A.LatinFont { Typeface = "Arial" },
                        new A.EastAsianFont { Typeface = string.Empty },
                        new A.ComplexScriptFont { Typeface = string.Empty }),
                    new A.MinorFont(
                        new A.LatinFont { Typeface = "Arial" },
                        new A.EastAsianFont { Typeface = string.Empty },
                        new A.ComplexScriptFont { Typeface = string.Empty }))
                { Name = "DocCopyCli Fonts" },
                new A.FormatScheme(
                    new A.FillStyleList(
                        new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.PhColor }),
                        new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.Accent1 }),
                        new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.Accent2 })),
                    new A.LineStyleList(
                        new A.Outline(new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.PhColor })) { Width = 9525 },
                        new A.Outline(new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.Accent1 })) { Width = 25400 },
                        new A.Outline(new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.Accent2 })) { Width = 38100 }),
                    new A.EffectStyleList(new A.EffectStyle(), new A.EffectStyle(), new A.EffectStyle()),
                    new A.BackgroundFillStyleList(
                        new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.PhColor }),
                        new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.Accent1 }),
                        new A.SolidFill(new A.SchemeColor { Val = A.SchemeColorValues.Accent2 })))
                { Name = "DocCopyCli Formats" }),
            new A.ObjectDefaults(),
            new A.ExtraColorSchemeList())
        { Name = "DocCopyCli Theme" };
        themePart.Theme.Save();
    }

    private static void EnsureDirectory(string filePath)
    {
        string? dir = Path.GetDirectoryName(filePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }

    private static string SanitizeXmlText(string value)
    {
        var sb = new StringBuilder(value.Length);

        for (int i = 0; i < value.Length; i++)
        {
            char ch = value[i];
            if (char.IsHighSurrogate(ch))
            {
                if (i + 1 < value.Length && char.IsLowSurrogate(value[i + 1]))
                {
                    sb.Append(ch);
                    sb.Append(value[++i]);
                }

                continue;
            }

            if (char.IsLowSurrogate(ch)) continue;
            if (IsValidXmlChar(ch)) sb.Append(ch);
        }

        return sb.ToString();
    }

    private static bool IsValidXmlChar(char ch)
        => ch == '\t' || ch == '\n' || ch == '\r' ||
           (ch >= ' ' && ch <= '\uD7FF') ||
           (ch >= '\uE000' && ch <= '\uFFFD');
}
