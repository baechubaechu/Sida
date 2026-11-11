using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Linq;
using Eto.Drawing;
using Eto.Forms;
using Rhino;

namespace SidaRhino
{
    /// <summary>One layer in the panel's table: its name, the meaning the designer gave, the floor height.</summary>
    public sealed class LayerRow
    {
        public int Index { get; set; }
        public string Path { get; set; } = "";
        public string Meaning { get; set; } = "";
        public string FloorHeight { get; set; } = "";
    }

    /// <summary>
    /// The Sida panel (v1, native): which Sida project this document belongs to, each layer's
    /// meaning and floor height, pull and push, and the figures Sida answered. All words on it
    /// are Korean; the figures come from Sida and are shown as sent.
    /// </summary>
    [System.Runtime.InteropServices.Guid("8E2D5C1A-7B3F-4E6A-9C2D-1F4B7A9E3D21")]
    public class SidaPanel : Panel
    {
        public static Guid PanelId => typeof(SidaPanel).GUID;

        private readonly uint _documentSerialNumber;
        private readonly SidaClient _client = new SidaClient();
        private readonly DropDown _projects = new DropDown();
        private readonly Label _status = new Label { Text = "Sida에 연결하는 중…" };
        private readonly GridView _layers = new GridView { Height = 220 };
        private readonly TextArea _figures = new TextArea { ReadOnly = true, Height = 140, Wrap = true };
        private readonly ObservableCollection<LayerRow> _rows = new ObservableCollection<LayerRow>();
        private IReadOnlyList<Meaning> _meanings = Array.Empty<Meaning>();
        private IReadOnlyList<SidaProject> _projectList = Array.Empty<SidaProject>();
        private bool _filling;

        public SidaPanel(uint documentSerialNumber)
        {
            _documentSerialNumber = documentSerialNumber;
            var refresh = new Button { Text = "새로 고침" };
            var pull = new Button { Text = "Sida에서 가져오기" };
            var push = new Button { Text = "Sida로 보내기" };
            var figures = new Button { Text = "수치만 보기" };
            refresh.Click += (s, e) => Refresh();
            pull.Click += (s, e) => Run("SidaPull");
            push.Click += (s, e) => Run("SidaPush");
            figures.Click += (s, e) => ShowFigures();
            _projects.SelectedValueChanged += (s, e) => ProjectPicked();

            _layers.DataStore = _rows;
            _layers.Columns.Add(new GridColumn { HeaderText = "레이어", Editable = false, Width = 160,
                DataCell = new TextBoxCell { Binding = Binding.Property((LayerRow r) => r.Path) } });
            _layers.Columns.Add(new GridColumn { HeaderText = "의미", Editable = true, Width = 110,
                DataCell = new ComboBoxCell
                {
                    Binding = Binding.Delegate<LayerRow, object>(r => r.Meaning, (r, value) => r.Meaning = value as string ?? ""),
                    DataStore = MeaningItems(),
                } });
            _layers.Columns.Add(new GridColumn { HeaderText = "층고 (m)", Editable = true, Width = 70,
                DataCell = new TextBoxCell { Binding = Binding.Property((LayerRow r) => r.FloorHeight) } });
            _layers.CellEdited += (s, e) => RowEdited(e.Item as LayerRow);

            Content = new TableLayout
            {
                Padding = new Padding(8),
                Spacing = new Size(6, 6),
                Rows =
                {
                    new TableRow(new Label { Text = "프로젝트" }, _projects),
                    new TableRow(_status) { ScaleHeight = false },
                    new TableRow(new StackLayout { Orientation = Orientation.Horizontal, Spacing = 6, Items = { pull, push, figures, refresh } }),
                    new TableRow(new Label { Text = "레이어 의미 (의미 없는 레이어는 수치에서 빠집니다)" }),
                    new TableRow(_layers) { ScaleHeight = true },
                    new TableRow(new Label { Text = "Sida가 계산한 수치" }),
                    new TableRow(_figures),
                },
            };
            Refresh();
        }

        private RhinoDoc? Doc => RhinoDoc.FromRuntimeSerialNumber(_documentSerialNumber) ?? RhinoDoc.ActiveDoc;

        private List<IListItem> MeaningItems()
        {
            var items = new List<IListItem> { new ListItem { Key = "", Text = "(의미 없음)" } };
            foreach (var m in _meanings)
                items.Add(new ListItem { Key = m.Code, Text = m.Built ? m.Word : $"{m.Word} · 수치 제외" });
            return items;
        }

        /// <summary>Ask Sida whether it is up, list its projects, and read this document's layers.</summary>
        public void Refresh()
        {
            try
            {
                var meanings = _client.Hello();
                if (meanings == null)
                {
                    _status.Text = "Sida 앱이 꺼져 있습니다. run.bat으로 켠 뒤 '새로 고침'을 누르세요.";
                    _projects.Enabled = false;
                    return;
                }
                _meanings = meanings;
                ((ComboBoxCell)_layers.Columns[1].DataCell).DataStore = MeaningItems();
                _projectList = _client.Projects();
                _status.Text = $"Sida 연결됨 ({_client.BaseUrl}), 프로젝트 {_projectList.Count}개";
                _projects.Enabled = true;
            }
            catch (SidaException exc)
            {
                _status.Text = exc.Message;
                return;
            }
            var doc = Doc;
            var current = doc != null ? Meanings.Project(doc) : null;
            _filling = true;
            _projects.Items.Clear();
            _projects.Items.Add(new ListItem { Key = "", Text = "(프로젝트를 고르세요)" });
            foreach (var p in _projectList)
                _projects.Items.Add(new ListItem { Key = p.Name, Text = p.DisplayName == p.Name ? p.Name : $"{p.DisplayName} ({p.Name})" });
            _projects.SelectedKey = current != null && _projectList.Any(p => p.Name == current) ? current : "";
            _filling = false;
            FillLayers();
        }

        private void FillLayers()
        {
            var doc = Doc;
            _rows.Clear();
            if (doc == null)
                return;
            var toMetres = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters);
            foreach (var (layer, meaning, floorHeight) in Meanings.All(doc))
            {
                _rows.Add(new LayerRow
                {
                    Index = layer.Index, Path = layer.FullPath, Meaning = meaning,
                    FloorHeight = floorHeight.HasValue ? (floorHeight.Value * toMetres).ToString("0.##", CultureInfo.InvariantCulture) : "",
                });
            }
        }

        private void ProjectPicked()
        {
            if (_filling)
                return;
            var doc = Doc;
            var key = _projects.SelectedKey ?? "";
            if (doc == null || string.IsNullOrEmpty(key))
                return;
            Meanings.SetProject(doc, key);
            _status.Text = $"이 문서는 Sida 프로젝트 '{key}'에 연결됐습니다 (문서에 저장됨).";
        }

        private void RowEdited(LayerRow? row)
        {
            var doc = Doc;
            if (row == null || doc == null)
                return;
            double? height = null;
            if (double.TryParse(row.FloorHeight, NumberStyles.Float, CultureInfo.InvariantCulture, out var metres) && metres > 0)
                height = metres / RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters);
            else
                row.FloorHeight = "";
            Meanings.Set(doc, row.Index, row.Meaning ?? "", height);
        }

        private void Run(string command)
        {
            RhinoApp.RunScript($"_{command}", false);
            if (command == "SidaPush")
                ShowFigures();
        }

        /// <summary>Figures for the document as it is now, without saving a snapshot.</summary>
        private void ShowFigures()
        {
            var doc = Doc;
            var project = doc != null ? Meanings.Project(doc) : null;
            if (doc == null || project == null)
            {
                _figures.Text = "먼저 프로젝트를 고르세요.";
                return;
            }
            try
            {
                var answer = _client.Figures(project, SnapshotBuilder.Build(doc, withMeshes: false));
                _figures.Text = string.Join(Environment.NewLine, answer.Lines);
            }
            catch (SidaException exc)
            {
                _figures.Text = exc.Message;
            }
        }
    }
}
