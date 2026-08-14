#target photoshop
app.bringToFront();

// ================= 全局變數 =================
var stopFlag = false;

// ================= UI構建 =================
var dlg = new Window("dialog", "PSD 批量導出工具");
dlg.orientation = "column";
dlg.alignChildren = ["fill", "top"];
dlg.preferredSize.width = 500;

// ======= 頂部按鈕 =======
var topGroup = dlg.add("group");
topGroup.alignment = ["fill", "top"];
var title = topGroup.add("statictext", undefined, "PSD 批量導出工具");
title.graphics.font = ScriptUI.newFont("Arial", "BOLD", 14);
topGroup.add("statictext", undefined, ""); // spacer
var closeBtn = topGroup.add("button", undefined, "關閉");
closeBtn.onClick = function () {
    stopFlag = true;
    dlg.close();
};



// 獲取 Photoshop 工作文件夾的綜合方法
function getPhotoshopCurrentFolder() {
    var possibleFolders = [];
    
    // 方法1: 當前打開的文件
    try {
        if (app.documents.length > 0 && app.activeDocument && app.activeDocument.path) {
            possibleFolders.push(new Folder(app.activeDocument.path));
        }
    } catch (e) {}
    
    // 方法2: 最近打開的文件
    try {
        if (app.recentFiles.length > 0) {
            for (var i = 0; i < Math.min(app.recentFiles.length, 5); i++) {
                var recentFile = app.recentFiles[i];
                if (recentFile && recentFile.fsName) {
                    var recentFolder = new File(recentFile.fsName).parent;
                    if (recentFolder.exists) {
                        possibleFolders.push(recentFolder);
                    }
                }
            }
        }
    } catch (e) {}
    
    // 方法3: 原有的 getLastOpenedFolder()（如果存在的話）
    try {
        if (typeof getLastOpenedFolder === 'function') {
            var lastFolder = getLastOpenedFolder();
            if (lastFolder && lastFolder.exists) {
                possibleFolders.push(lastFolder);
            }
        }
    } catch (e) {}
    
    // 方法4: 檢查是否有常用的工作文件夾
    var commonFolders = [
        Folder.desktop,
        Folder.myPictures,
        new Folder(Folder.desktop.fsName + "/工作"),
        new Folder(Folder.desktop.fsName + "/projects")
    ];
    
    possibleFolders = possibleFolders.concat(commonFolders);
    
    // 返回第一個存在的文件夾
    for (var i = 0; i < possibleFolders.length; i++) {
        if (possibleFolders[i] && possibleFolders[i].exists) {
            return possibleFolders[i];
        }
    }
    
    // 所有都失敗時返回桌面
    return Folder.desktop;
}




// ======= PSD 文件夾選擇 =======
var folderGroup = dlg.add("group");
folderGroup.alignment = ["left", "top"];
folderGroup.add("statictext", undefined, "PSD 文件夾：");
var folderBar = folderGroup.add("edittext", undefined, "");
folderBar.characters = 38;
folderBar.enabled = true;
folderBar.readonly = true;
var folderBtn = folderGroup.add("button", undefined, "選擇...");
var psdFolder = null;
folderBtn.onClick = function () {
    var start = getPhotoshopCurrentFolder();
    // 如果之前已選擇過 PSD 文件夾則優先使用它，否則使用 start
    var defaultFolder = (psdFolder && psdFolder.exists) ? psdFolder : start;
    var folder = Folder.selectDialog("選擇PSD文件所在的資料夾", defaultFolder);
    if (folder) {
        psdFolder = folder;
        folderBar.text = psdFolder.fsName;
    }
};

// ======= 導出文件夾選擇 =======
var outGroup = dlg.add("group");
outGroup.alignment = ["left", "top"];
outGroup.add("statictext", undefined, "導出文件夾：");
var outBar = outGroup.add("edittext", undefined, "");
outBar.characters = 38;
outBar.enabled = true;
outBar.readonly = true;
var outBtn = outGroup.add("button", undefined, "選擇...");
var exportFolder = null;
outBtn.onClick = function () {
    var start = getPhotoshopCurrentFolder();
    // 优先使用已选择的导出文件夹，其次使用已选择的 PSD 文件夹，最后使用 start
    var defaultFolder = (exportFolder && exportFolder.exists) ? exportFolder : ((psdFolder && psdFolder.exists) ? psdFolder : start);
    var folder = Folder.selectDialog("選擇導出圖片的資料夾", defaultFolder);
    if (folder) {
        exportFolder = folder;
        outBar.text = exportFolder.fsName;
    }
};

// ======= 導出設置 =======
dlg.add("panel", undefined, "導出選項");

// 格式選擇
var formatGroup = dlg.add("group");
formatGroup.add("statictext", undefined, "導出格式：");
var formatDropdown = formatGroup.add("dropdownlist", undefined, ["PNG", "JPG"]);
formatDropdown.selection = 0;

// 色彩空間
var colorSpaceGroup = dlg.add("group");
colorSpaceGroup.add("statictext", undefined, "色彩空間：");
var colorDropdown = colorSpaceGroup.add("dropdownlist", undefined, ["RGB", "灰階", "索引"]);
colorDropdown.selection = 0;

// 位深
var bitDepthGroup = dlg.add("group");
bitDepthGroup.add("statictext", undefined, "位深：");
var bitDropdown = bitDepthGroup.add("dropdownlist", undefined, ["8", "16", "32"]);
bitDropdown.selection = 0;

// PNG / JPG 特定選項面板
var optPanel = dlg.add("panel", undefined, "格式選項");
optPanel.orientation = "column";
optPanel.alignChildren = ["fill", "top"];

// PNG最小存儲（說明：Photoshop 原生 PNGSaveOptions 只有 interlaced 等基本選項，
// 若需更細的最小化處理通常用 Save For Web 或外部工具。此選項僅作為標記。）
var pngSmallest = optPanel.add("checkbox", undefined, "PNG：最小存儲空間（標記）");
pngSmallest.value = true;

// JPG PPI 與壓縮比
var jpgRow = optPanel.add("group");
jpgRow.add("statictext", undefined, "JPG 壓縮品質 (1-12)：");
var jpgQuality = jpgRow.add("edittext", undefined, "12");
jpgQuality.characters = 3;

// ======= 狀態 / 控制 =======
var statusGroup = dlg.add("group");
statusGroup.alignment = ["fill", "top"];
var statusLabel = statusGroup.add("statictext", undefined, "狀態：等待操作");

// ======= 開始導出按鈕 =======
var runGroup = dlg.add("group");
runGroup.alignment = ["center", "top"];
var runBtn = runGroup.add("button", undefined, "開始導出", { name: "ok" });

// ================= 功能邏輯 =================
function updateStatus(s) {
    try { statusLabel.text = "狀態：" + s; } catch (e) {}
}

runBtn.onClick = function () {
    // 先檢查輸入
    if (!psdFolder) {
        alert("請先選擇 PSD 文件夾！");
        return;
    }
    if (!exportFolder) {
        alert("請先選擇 導出文件夾！");
        return;
    }

    stopFlag = false;
    updateStatus("開始掃描 PSD 文件...");
    var files = psdFolder.getFiles(function (f) { return f instanceof File && /\.psd$/i.test(f.name); });
    if (!files || files.length === 0) {
        alert("在所選 PSD 文件夾中未找到 PSD 文件！");
        updateStatus("未找到 PSD 文件");
        return;
    }

    // 確保導出文件夾存在
    if (!exportFolder.exists) {
        try { exportFolder.create(); } catch (e) { alert("無法創建導出文件夾：" + e.message); return; }
    }

    updateStatus("開始導出，共 " + files.length + " 個文件");
    for (var i = 0; i < files.length; i++) {
        if (stopFlag) break;
        var file = files[i];
        updateStatus("處理：" + file.name + "（" + (i+1) + "/" + files.length + "）");
        try {
            var doc = app.open(file);

            // 設置位深（注意：某些模式/位深轉換可能不被允許或會提示）
            try {
                switch (bitDropdown.selection.text) {
                    case "8": doc.bitsPerChannel = BitsPerChannelType.EIGHT; break;
                    case "16": doc.bitsPerChannel = BitsPerChannelType.SIXTEEN; break;
                    case "32": doc.bitsPerChannel = BitsPerChannelType.THIRTYTWO; break;
                }
            } catch (e) {
                // 忽略位深設置錯誤但記錄
                $.writeln("bit depth change failed for " + file.name + ": " + e.message);
            }

            // 設置色彩空間
            try {
                switch (colorDropdown.selection.text) {
                    case "灰階": doc.changeMode(ChangeMode.GRAYSCALE); break;
                    case "索引": doc.changeMode(ChangeMode.INDEXEDCOLOR); break;
                    default: doc.changeMode(ChangeMode.RGB); break;
                }
            } catch (e) {
                $.writeln("color mode change failed for " + file.name + ": " + e.message);
            }

            // 準備輸出路徑與名字
            var baseName = decodeURI(file.name).replace(/\.[^\.]+$/, "");
            var outFile;

            if (formatDropdown.selection.text === "PNG") {
                outFile = new File(exportFolder.fsName + "/" + baseName + ".png");
                var pngOpt = new PNGSaveOptions();
                pngOpt.interlaced = false;
                // 注意：Photoshop 的 PNGSaveOptions 沒有直接的“最小存儲空間”屬性，
                // 需要更高級壓縮需使用 Save For Web 或外部優化工具。此處僅保存為 PNG。
                doc.saveAs(outFile, pngOpt, true, Extension.LOWERCASE);
            } else { // JPG
                outFile = new File(exportFolder.fsName + "/" + baseName + ".jpg");
                var jpgOpt = new JPEGSaveOptions();
                var q = parseInt(jpgQuality.text, 10);
                if (isNaN(q)) q = 12;
                if (q < 1) q = 1;
                if (q > 12) q = 12;
                jpgOpt.quality = q;
                // PPI 處理若需改變可在這裡增加 doc.resizeImage 或改變 doc.resolution
                doc.saveAs(outFile, jpgOpt, true, Extension.LOWERCASE);
            }

            doc.close(SaveOptions.DONOTSAVECHANGES);
        } catch (e) {
            alert("導出失敗：" + file.name + "\n" + e.message);
        }
    }

    updateStatus(stopFlag ? "導出已中止。" : "全部導出完成！");
    alert(stopFlag ? "導出已中止。" : "全部導出完成！");
};

// 若按 Esc 或關閉窗體會設置 stopFlag
dlg.addEventListener("close", function () { stopFlag = true; });

// ================= 顯示對話框 =================
dlg.center();
dlg.show();
