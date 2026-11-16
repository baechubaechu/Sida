using System;
using Eto.Drawing;
using Eto.Forms;

namespace SidaRhino
{
    /// <summary>
    /// The Sida panel: a web view on Sida's own page for Rhino (webui/app/rhino.html), which shows
    /// the figures, the layers' meanings and the pull and push buttons. Nothing of that is drawn
    /// here; the page talks to Sida and Sida talks to this plugin (LiveLink). What is native is
    /// only what the page cannot say: that Sida is not running, or that this Rhino cannot show a
    /// web view, with a way to open the page in a browser instead.
    /// </summary>
    [System.Runtime.InteropServices.Guid("8E2D5C1A-7B3F-4E6A-9C2D-1F4B7A9E3D21")]
    public class SidaPanel : Panel
    {
        public static Guid PanelId => typeof(SidaPanel).GUID;

        private const string SidaOff = "Sida 앱이 꺼져 있습니다. Sida를 켜면(run.bat) 이 패널이 저절로 이어집니다.";
        private const string NoWebView = "이 라이노에서는 패널 화면을 안에 띄울 수 없습니다. 아래 단추로 브라우저에서 열면 똑같이 쓸 수 있습니다.";

        private readonly WebView? _web;
        private readonly Label _words = new Label { Wrap = WrapMode.Word };
        private readonly Button _browser = new Button { Text = "브라우저에서 열기" };
        private readonly StackLayout _aside;
        private readonly UITimer _timer = new UITimer { Interval = 1.0 };
        private bool _webShown;
        private bool _wasUp;

        public SidaPanel(uint documentSerialNumber)
        {
            try
            {
                _web = new WebView { BrowserContextMenuEnabled = false };
            }
            catch (Exception)
            {
                _web = null;  // no web view on this machine: the page still opens in a browser
            }
            _browser.Click += (s, e) => LiveLink.OpenInBrowser();
            _aside = new StackLayout { Padding = new Padding(16), Spacing = 12, Items = { _words, _browser } };
            Content = _aside;
            LiveLink.Ensure();
            _timer.Elapsed += (s, e) => Follow();
            _timer.Start();
            Follow();
        }

        /// <summary>Once a second: show the page while Sida answers, the plain words while it does not.</summary>
        private void Follow()
        {
            var up = LiveLink.Up;
            if (up && _web != null)
            {
                if (!_wasUp)
                    _web.Url = new Uri(LiveLink.PanelUrl);  // also after Sida came back: it may be a newer Sida
                if (!_webShown)
                {
                    Content = _web;
                    _webShown = true;
                }
            }
            else if (!_webShown)
            {
                // Once the page is up it says itself that Sida went away, so it stays.
                var words = up ? NoWebView : LiveLink.Problem ?? SidaOff;
                if (_words.Text != words)
                    _words.Text = words;
                _browser.Visible = up;
            }
            _wasUp = up;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
                _timer.Stop();
            base.Dispose(disposing);
        }
    }
}
