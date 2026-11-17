package com.studybridge.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.method.ScrollingMovementMethod;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/**
 * 学习桥梁 Android 外壳。
 *
 * 这个 APK 只是"套壳浏览器"：它打开你自己 AstrBot 上的 http://<IP>:6188/study/。
 * 因此白屏时最重要的不是猜，而是把"为什么白"显示出来 —— 本类会在页面加载后
 * 检查 #app 是否渲染出内容，为空就切到诊断页，显示 WebView 版本、JS 报错、HTTP 错误。
 *
 * 没有 androidx 依赖：只用系统 API，便于 aapt2 + javac + d8 直接打包。
 */
public class MainActivity extends Activity {

    private static final String PREFS = "study_bridge";
    private static final String KEY_SERVER = "server";
    private static final String SCHEME_RESET = "studybridge://reset";
    private static final int PINK = 0xFFD6336C;
    private static final int INK = 0xFF2A1B22;
    private static final int INK_DIM = 0xFF8B6B77;
    private static final int PAGE_BG = 0xFFFFF7FA;
    private static final int FIELD_BG = 0xFFFFFFFF;
    private static final int FIELD_LINE = 0xFFE8C2D1;

    private WebView webView;
    private FrameLayout container;
    private LinearLayout loadingPanel;
    private TextView loadingView;
    private TextView loadingNote;
    private SharedPreferences prefs;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final List<String> consoleErrors = new ArrayList<String>();
    private final List<String> httpErrors = new ArrayList<String>();
    private String currentBase = "";
    private String lastReason = "";
    private int renderAttempts = 0;
    private boolean diagnosticsShown = false;

    /** 打开慢时把「正在打开」换成更具体的提示，避免用户对着空白页猜。 */
    private final Runnable loadingHint = new Runnable() {
        @Override
        public void run() {
            if (!loadingVisible()) {
                return;
            }
            loadingNote.setText("网络慢，或者那台机器没响应。可以点「看原因」或「退出 App」。");
        }
    };

    /** 12 秒还没打开就直接给诊断页：不让人一直盯着空白。 */
    private final Runnable loadingTimeout = new Runnable() {
        @Override
        public void run() {
            if (!loadingVisible()) {
                return;
            }
            showDiagnostics("页面 12 秒没有响应：地址不通，或者那台机器卡住了");
        }
    };

    private boolean loadingVisible() {
        return loadingPanel != null && loadingPanel.getVisibility() == View.VISIBLE;
    }

    /**
     * 页面加载完后检查是否真的渲染了内容；渲染不出来就展示诊断页。
     * 1.2s 先看一眼，之后 +2s、+3s 再补两次（最迟 ~6s 给结论），
     * 既不会让慢手机被误判成白屏，也不用等几十秒才知道坏在哪。
     */
    private final Runnable renderCheck = new Runnable() {
        @Override
        public void run() {
            if (webView == null || diagnosticsShown || isFinishing()) {
                return;
            }
            renderAttempts++;
            webView.evaluateJavascript(
                    "(function(){var e=document.getElementById('app');"
                            + "if(!e){return '-1'}return e.children.length+'/'+e.innerHTML.length})()",
                    new android.webkit.ValueCallback<String>() {
                        @Override
                        public void onReceiveValue(String value) {
                            String cleaned = value == null ? "" : value.replace("\"", "").trim();
                            boolean blank = cleaned.isEmpty() || cleaned.equals("-1");
                            if (!blank) {
                                String[] parts = cleaned.split("/");
                                int children = 0;
                                int length = 0;
                                try {
                                    children = Integer.parseInt(parts[0]);
                                    length = parts.length > 1 ? Integer.parseInt(parts[1]) : 0;
                                } catch (NumberFormatException ignored) {
                                    blank = true;
                                }
                                // 只有空壳（例如 <div id="app"><!-- --></div>）也算没渲染
                                blank = blank || children == 0 || length < 200;
                            }
                            if (!blank) {
                                return;
                            }
                            if (renderAttempts < 3) {
                                handler.postDelayed(renderCheck, renderAttempts == 1 ? 2000 : 3000);
                            } else {
                                showDiagnostics("页面已经加载，但界面没有渲染出来");
                            }
                        }
                    });
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        webView = new WebView(this);
        configureWebView();
        buildContainer();
        applyStatusBar();
        try {
            WebView.setWebContentsDebuggingEnabled(true);
        } catch (Throwable ignored) {
            // 老系统没有这个开关，忽略
        }
        String server = prefs.getString(KEY_SERVER, "");
        if (server == null || server.trim().isEmpty()) {
            showSetup("");
        } else {
            openServer(server);
        }
    }

    // ------------------------------------------------------------ WebView

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        // 粉色是浅色设计：系统深色模式下的“强制深色”会把整页反相成脏灰，
        // 所以显式关掉算法调暗（API 33+ 才有这个开关）。
        if (Build.VERSION.SDK_INT >= 33) {
            try {
                settings.setAlgorithmicDarkeningAllowed(false);
            } catch (Throwable ignored) {
                // 个别定制 WebView 没有这个接口，忽略
            }
        }
        webView.setBackgroundColor(PAGE_BG);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage message) {
                if (message != null && message.messageLevel() == ConsoleMessage.MessageLevel.ERROR) {
                    addLine(consoleErrors, "JS: " + message.message() + " @" + message.lineNumber());
                }
                return true;
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(url);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleUrl(request == null ? null : String.valueOf(request.getUrl()));
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                renderAttempts = 0;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                hideLoading();
                handler.removeCallbacks(renderCheck);
                renderAttempts = 0;
                handler.postDelayed(renderCheck, 1200);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request != null && request.isForMainFrame()) {
                    String desc = error == null ? "未知网络错误" : String.valueOf(error.getDescription());
                    addLine(httpErrors, "网络：" + desc + " " + request.getUrl());
                    hideLoading();
                    showDiagnostics("连不上这台机器：" + desc);
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request == null || response == null) {
                    return;
                }
                String line = "HTTP " + response.getStatusCode() + " " + request.getUrl();
                addLine(httpErrors, line);
                if (request.isForMainFrame()) {
                    hideLoading();
                    showDiagnostics("服务器返回 " + response.getStatusCode() + "（页面打不开）");
                }
            }
        });

        webView.setOnLongClickListener(new View.OnLongClickListener() {
            @Override
            public boolean onLongClick(View v) {
                showMenu();
                return true;
            }
        });

        // 长按菜单在很旧的 WebView 上会被系统的长按选词吃掉，所以再给网页一个正规入口：
        // 设置页里的「换服务器地址」直接调用原生弹窗。只暴露这两个无副作用的动作。
        try {
            webView.addJavascriptInterface(new ShellBridge(), "StudyBridgeShell");
        } catch (Throwable ignored) {
            // 极老系统没有这个接口，忽略
        }
    }

    /** 网页 → 原生的窄接口：不读数据、不执行任意代码。 */
    private class ShellBridge {
        @JavascriptInterface
        public void changeServer() {
            handler.post(new Runnable() {
                @Override
                public void run() {
                    promptServer();
                }
            });
        }

        @JavascriptInterface
        public void reloadPage() {
            handler.post(new Runnable() {
                @Override
                public void run() {
                    if (webView != null) {
                        webView.reload();
                    }
                }
            });
        }
    }

    /** 自己定义 studybridge://reset 这种内部链接：换地址用，不进历史。 */
    private boolean handleUrl(String url) {
        if (url != null && url.startsWith(SCHEME_RESET)) {
            promptServer();
            return true;
        }
        return false;
    }

    private void openServer(String server) {
        String base = normalize(server);
        if (base == null) {
            showSetup("地址不能为空");
            return;
        }
        currentBase = base;
        diagnosticsShown = false;
        renderAttempts = 0;
        consoleErrors.clear();
        httpErrors.clear();
        prefs.edit().putString(KEY_SERVER, base).apply();
        setContentView(container);
        showLoading("正在打开 " + base + " …");
        webView.loadUrl(base + "/study/");
    }

    // ------------------------------------------------------------ 容器与提示

    /**
     * WebView + 居中的加载面板。
     *
     * 加载面板**一出现就带两个按钮**：「看原因」和「退出 App」——
     * 白屏时不用等任何超时就有出路（用户反馈：不要等三十秒才给界面）。
     */
    private void buildContainer() {
        container = new FrameLayout(this);
        container.setBackgroundColor(PAGE_BG);
        container.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        loadingPanel = new LinearLayout(this);
        loadingPanel.setOrientation(LinearLayout.VERTICAL);
        loadingPanel.setGravity(Gravity.CENTER_HORIZONTAL);
        loadingPanel.setPadding(dp(28), dp(20), dp(28), dp(20));

        loadingView = new TextView(this);
        loadingView.setText("正在打开 …");
        loadingView.setTextSize(14f);
        loadingView.setTextColor(INK);
        loadingView.setGravity(Gravity.CENTER);
        loadingView.setLineSpacing(dp(4), 1f);
        loadingPanel.addView(loadingView);

        loadingNote = new TextView(this);
        loadingNote.setText("正在连那台机器，还没返回");
        loadingNote.setTextSize(12f);
        loadingNote.setTextColor(INK_DIM);
        loadingNote.setGravity(Gravity.CENTER);
        loadingNote.setPadding(0, dp(6), 0, dp(2));
        loadingPanel.addView(loadingNote);

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.CENTER);

        Button reason = new Button(this);
        reason.setText("看原因");
        reason.setTextColor(PINK);
        reason.setTextSize(13f);
        reason.setAllCaps(false);
        reason.setBackground(makeBox(0x00FFFFFF, FIELD_LINE, 10));
        reason.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showDiagnostics("打开过程中我点了「看原因」");
            }
        });
        LinearLayout.LayoutParams reasonParams = new LinearLayout.LayoutParams(dp(104), dp(42));
        reasonParams.rightMargin = dp(10);
        actions.addView(reason, reasonParams);

        Button quit = new Button(this);
        quit.setText("退出 App");
        quit.setTextColor(INK);
        quit.setTextSize(13f);
        quit.setAllCaps(false);
        quit.setBackground(makeBox(0x00FFFFFF, FIELD_LINE, 10));
        quit.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });
        actions.addView(quit, new LinearLayout.LayoutParams(dp(104), dp(42)));

        loadingPanel.addView(actions, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.gravity = Gravity.CENTER;
        container.addView(loadingPanel, params);
    }

    private void showLoading(String text) {
        if (loadingPanel == null) {
            return;
        }
        loadingView.setText(text);
        loadingNote.setText("正在连那台机器，还没返回");
        loadingPanel.setVisibility(View.VISIBLE);
        handler.removeCallbacks(loadingHint);
        handler.removeCallbacks(loadingTimeout);
        handler.postDelayed(loadingHint, 5000);
        handler.postDelayed(loadingTimeout, 12000);
    }

    private void hideLoading() {
        if (loadingPanel == null) {
            return;
        }
        handler.removeCallbacks(loadingHint);
        handler.removeCallbacks(loadingTimeout);
        loadingPanel.setVisibility(View.GONE);
    }

    /** 状态栏跟着粉色页面走，别在浅色页面上压一条深灰。 */
    private void applyStatusBar() {
        try {
            getWindow().setStatusBarColor(PAGE_BG);
            if (Build.VERSION.SDK_INT >= 23) {
                getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
            }
        } catch (Throwable ignored) {
            // 老系统/定制 ROM 上失败就算了，不影响功能
        }
    }

    private String normalize(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) {
            return null;
        }
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://" + value;
        }
        while (value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }

    // ------------------------------------------------------------ 首次配置页

    private void showSetup(String notice) {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(PAGE_BG);
        root.setPadding(dp(24), dp(44), dp(24), dp(24));

        TextView title = new TextView(this);
        title.setText("学习桥梁");
        title.setTextSize(24f);
        title.setTextColor(INK);
        root.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("填你自己的 AstrBot 插件地址，数据只存在那台机器上");
        subtitle.setTextSize(13f);
        subtitle.setTextColor(INK_DIM);
        subtitle.setPadding(0, dp(6), 0, dp(16));
        root.addView(subtitle);

        if (notice != null && !notice.isEmpty()) {
            TextView warn = new TextView(this);
            warn.setText(notice);
            warn.setTextSize(12f);
            warn.setTextColor(0xFFB02A57);
            warn.setPadding(0, 0, 0, dp(10));
            root.addView(warn);
        }

        EditText input = new EditText(this);
        input.setHint("http://192.168.1.10:6188");
        input.setText(prefs.getString(KEY_SERVER, ""));
        input.setTextSize(15f);
        input.setTextColor(INK);
        input.setSingleLine(true);
        input.setInputType(android.text.InputType.TYPE_CLASS_TEXT
                | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        input.setImeOptions(EditorInfo.IME_ACTION_GO);
        input.setBackground(makeBox(FIELD_BG, FIELD_LINE, 10));
        input.setPadding(dp(14), dp(12), dp(14), dp(12));
        root.addView(input, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button connect = new Button(this);
        connect.setText("连接");
        connect.setTextColor(Color.WHITE);
        connect.setTextSize(15f);
        connect.setAllCaps(false);
        connect.setBackground(makeBox(PINK, PINK, 10));
        LinearLayout.LayoutParams connectParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(46));
        connectParams.topMargin = dp(14);
        root.addView(connect, connectParams);

        Button browser = new Button(this);
        browser.setText("先用系统浏览器打开试试");
        browser.setTextColor(PINK);
        browser.setTextSize(13f);
        browser.setAllCaps(false);
        browser.setBackground(makeBox(0x00FFFFFF, FIELD_LINE, 10));
        LinearLayout.LayoutParams browserParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(42));
        browserParams.topMargin = dp(10);
        root.addView(browser, browserParams);

        TextView help = new TextView(this);
        help.setText("连接后在网页里生成 6 位绑定码，再在 QQ 里私聊机器人发 /bind 123456。\n"
                + "连不上时先用系统浏览器打开同一地址：浏览器能开说明地址没问题，是 App 的问题；"
                + "浏览器也打不开就是服务端/端口/防火墙的问题。\n\n"
                + "WebView 版本：" + shortUserAgent());
        help.setTextSize(12f);
        help.setTextColor(INK_DIM);
        help.setPadding(0, dp(16), 0, 0);
        help.setLineSpacing(dp(4), 1f);
        root.addView(help);

        final EditText field = input;
        connect.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String value = normalize(field.getText().toString());
                if (value == null) {
                    toast("先填地址，例如 http://192.168.1.10:6188");
                    return;
                }
                openServer(value);
            }
        });
        browser.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String value = normalize(field.getText().toString());
                if (value == null) {
                    toast("先填地址");
                    return;
                }
                openInBrowser(value);
            }
        });

        setContentView(root);
        input.requestFocus();
    }

    private void promptServer() {
        final EditText field = new EditText(this);
        field.setText(prefs.getString(KEY_SERVER, ""));
        field.setHint("http://192.168.1.10:6188");
        field.setSingleLine(true);
        field.setInputType(android.text.InputType.TYPE_CLASS_TEXT
                | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        new AlertDialog.Builder(this)
                .setTitle("换一个地址")
                .setView(field)
                .setPositiveButton("连接", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        String value = normalize(field.getText().toString());
                        if (value == null) {
                            toast("地址不能为空");
                            return;
                        }
                        openServer(value);
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    // ------------------------------------------------------------ 诊断页

    private void showDiagnostics(String reason) {
        if (isFinishing()) {
            return;
        }
        diagnosticsShown = true;
        lastReason = reason;
        handler.removeCallbacks(renderCheck);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(PAGE_BG);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(22), dp(36), dp(22), dp(24));
        scroll.addView(root);

        TextView title = new TextView(this);
        title.setText("页面没能打开");
        title.setTextSize(22f);
        title.setTextColor(INK);
        root.addView(title);

        TextView brief = new TextView(this);
        brief.setText(reason == null ? "" : reason);
        brief.setTextSize(14f);
        brief.setTextColor(0xFFB02A57);
        brief.setPadding(0, dp(8), 0, dp(14));
        root.addView(brief);

        TextView detail = new TextView(this);
        detail.setText(buildDiagnosticsText());
        detail.setTextSize(12f);
        detail.setTextColor(INK_DIM);
        detail.setTypeface(android.graphics.Typeface.MONOSPACE);
        detail.setMovementMethod(new ScrollingMovementMethod());
        detail.setBackground(makeBox(FIELD_BG, FIELD_LINE, 10));
        detail.setPadding(dp(12), dp(10), dp(12), dp(10));
        root.addView(detail);

        addAction(root, "重新加载", PINK, Color.WHITE, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openServer(currentBase);
            }
        });
        addAction(root, "在系统浏览器里打开", 0x00FFFFFF, PINK, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openInBrowser(currentBase);
            }
        });
        addAction(root, "换一个地址", 0x00FFFFFF, PINK, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                promptServer();
            }
        });
        addAction(root, "复制诊断信息", 0x00FFFFFF, PINK, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                copyText(buildDiagnosticsText());
            }
        });
        addAction(root, "退出 App", 0x00FFFFFF, PINK, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });

        setContentView(scroll);
    }

    private String buildDiagnosticsText() {
        StringBuilder builder = new StringBuilder();
        builder.append("地址：").append(currentBase).append("/study/\n");
        builder.append("WebView：").append(shortUserAgent()).append("\n");
        builder.append("检测结论：").append(lastReason).append("\n");
        if (chromeMajor() > 0 && chromeMajor() < 61) {
            builder.append("版本提示：WebView 低于 Chrome 61，属于很旧的系统内核；"
                    + "本 App 已内置旧内核兼容包，若仍是空白，请先更新系统里的「Android System WebView」。\n");
        }
        builder.append("\n—— JS 报错 ——\n");
        if (consoleErrors.isEmpty()) {
            builder.append("（无）\n");
        } else {
            for (int i = 0; i < consoleErrors.size() && i < 6; i++) {
                builder.append("· ").append(consoleErrors.get(i)).append("\n");
            }
        }
        builder.append("\n—— 资源/HTTP ——\n");
        if (httpErrors.isEmpty()) {
            builder.append("（无）\n");
        } else {
            for (int i = 0; i < httpErrors.size() && i < 8; i++) {
                builder.append("· ").append(httpErrors.get(i)).append("\n");
            }
        }
        builder.append("\n排查顺序：\n");
        builder.append("1) 点「在系统浏览器里打开」：能开 → 问题在 App/WebView，把这段诊断发给开发者；\n");
        builder.append("2) 浏览器也打不开 → 服务端没起、端口/防火墙不通、或插件没装好；\n");
        builder.append("3) 若 WebView 很旧（Chrome < 61），到系统里更新「Android System WebView」。\n");
        return builder.toString();
    }

    private void addAction(LinearLayout root, String text, int bg, int fg, View.OnClickListener listener) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextColor(fg);
        button.setTextSize(14f);
        button.setAllCaps(false);
        button.setBackground(makeBox(bg, FIELD_LINE, 10));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(44));
        params.topMargin = dp(10);
        root.addView(button, params);
        button.setOnClickListener(listener);
    }

    private void showMenu() {
        new AlertDialog.Builder(this)
                .setItems(new CharSequence[]{"刷新", "换一个地址", "在系统浏览器里打开", "清空缓存并重载",
                                "查看诊断信息", "退出 App"},
                        new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface dialog, int which) {
                                if (which == 0) {
                                    webView.reload();
                                } else if (which == 1) {
                                    promptServer();
                                } else if (which == 2) {
                                    openInBrowser(currentBase);
                                } else if (which == 3) {
                                    webView.clearCache(true);
                                    webView.reload();
                                } else if (which == 4) {
                                    showDiagnostics("我长按打开了菜单并查看诊断");
                                } else {
                                    finish();
                                }
                            }
                        })
                .show();
    }

    private void openInBrowser(String base) {
        String url = (base == null ? "" : base) + "/study/";
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Throwable error) {
            toast("没有可用的浏览器");
        }
    }

    private void copyText(String text) {
        try {
            ClipboardManager manager = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (manager != null) {
                manager.setPrimaryClip(ClipData.newPlainText("study-bridge", text));
                toast("已复制");
            }
        } catch (Throwable ignored) {
            toast("复制失败");
        }
    }

    // ------------------------------------------------------------ 交互

    @Override
    public void onBackPressed() {
        if (!diagnosticsShown && webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }

    // ------------------------------------------------------------ 小工具

    private static void addLine(List<String> list, String line) {
        if (list.size() < 20) {
            list.add(line);
        }
    }

    private String shortUserAgent() {
        String ua = webView == null ? "" : webView.getSettings().getUserAgentString();
        if (ua == null) {
            return "未知";
        }
        int index = ua.indexOf("Chrome/");
        if (index < 0) {
            return ua.length() > 60 ? ua.substring(0, 60) : ua;
        }
        int end = ua.indexOf(" ", index);
        return ua.substring(index, end > 0 ? end : Math.min(ua.length(), index + 24));
    }

    /** Chrome/113.0.x → 113；取不到就返回 0。 */
    private int chromeMajor() {
        String ua = webView == null ? "" : webView.getSettings().getUserAgentString();
        if (ua == null) {
            return 0;
        }
        int index = ua.indexOf("Chrome/");
        if (index < 0) {
            return 0;
        }
        int start = index + 7;
        int end = start;
        while (end < ua.length() && Character.isDigit(ua.charAt(end))) {
            end++;
        }
        if (end == start) {
            return 0;
        }
        try {
            return Integer.parseInt(ua.substring(start, end));
        } catch (NumberFormatException error) {
            return 0;
        }
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density);
    }

    private GradientDrawable makeBox(int fill, int stroke, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(radiusDp));
        drawable.setStroke(dp(1), stroke);
        return drawable;
    }

    private void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show();
    }
}
