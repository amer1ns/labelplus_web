#target photoshop
app.bringToFront();

// ------------------- 版本信息 -------------------
// v5.5: 新增調試輸出、執行流程檢查、錯誤捕獲與進度修正

var stopFlag = false;
var debugEnabled = true;

function debugLog(msg) {
    if (!debugEnabled) return;
    try {
        if (typeof debugList !== 'undefined' && debugList != null) {
            debugList.text += msg + "\r";
            dlg.update();
        }
    } catch (e) {}
    try {
        $.writeln('[PS_PSD_v5.5] ' + msg);
    } catch (e) {}
}

function safeAlert(msg) {
    try {
        alert(msg);
    } catch (e) {}
}

function safeGetText(editText) {
    try {
        if (editText && editText.text != null) {
            return editText.text;
        }
    } catch (e) {
    }
    return "";
}

function trimString(value) {
    try {
        if (value == null) return "";
        var str = String(value);
        return str.replace(/^\s+|\s+$/g, "");
    } catch (e) {
        return "";
    }
}

function getLastOpenedFolder() {
    try {
        if (app.documents && app.documents.length > 0) {
            var docs = app.documents;
            var latestFolder = null;
            var latestTime = 0;
            for (var i = 0; i < docs.length; i++) {
                try {
                    var d = docs[i];
                    var f = null;
                    try { f = d.fullName; } catch (e) { f = null; }
                    if (f && f.exists) {
                        var mod = f.modified;
                        var t = (mod instanceof Date) ? mod.getTime() : new Date(mod).getTime();
                        if (t > latestTime) {
                            latestTime = t;
                            latestFolder = f.parent;
                        }
                    }
                } catch (e) {
                }
            }
            if (latestFolder) return latestFolder;
            try {
                if (app.activeDocument && app.activeDocument.path) return app.activeDocument.path;
            } catch (e) {}
        }
    } catch (e) {}
    return Folder.desktop;
}

var dlg = new Window("dialog", "PSD + 原圖批處理工具 v5.5");
dlg.orientation = "column";
dlg.alignChildren = ["fill", "top"];

var topGroup = dlg.add("group");
topGroup.alignment = "fill";
topGroup.orientation = "row";
topGroup.alignChildren = ["right","top"];
var closeBtn = topGroup.add("button", undefined, "關閉");

closeBtn.onClick = function() {
    stopFlag = true;
    dlg.close();
}

var psdGroup = dlg.add("group");
psdGroup.add("statictext", undefined, "PSD文件夾:");
var psdPathText = psdGroup.add("edittext", undefined, "");
psdPathText.characters = 30;
var psdBtn = psdGroup.add("button", undefined, "選擇PSD文件夾");

var imgGroup = dlg.add("group");
imgGroup.add("statictext", undefined, "原圖文件夾:");
var imgPathText = imgGroup.add("edittext", undefined, "");
imgPathText.characters = 30;
var imgBtn = imgGroup.add("button", undefined, "選擇原圖文件夾");

var sortChk = dlg.add("checkbox", undefined, "按照自然文件名排序");
var reverseChk = dlg.add("checkbox", undefined, "倒序插入原圖");

dlg.add("statictext", undefined, "PSD - 原圖 對比:");
var matchList = dlg.add("edittext", undefined, "", {multiline:true, readonly:true, scrollable:true});
matchList.preferredSize.height = 150;

var layerNameGroup = dlg.add("group");
layerNameGroup.add("statictext", undefined, "嵌入圖片圖層名字:");
var layerNameText = layerNameGroup.add("edittext", undefined, "元bg");
layerNameText.characters = 20;

dlg.add("statictext", undefined, "拉伸方式:");
var stretchGroup = dlg.add("group");
var stretchFit = stretchGroup.add("radiobutton", undefined, "保持比例填滿畫布");
var stretchNone = stretchGroup.add("radiobutton", undefined, "不保持比例拉伸至PSD畫布大小");
stretchFit.value = true;

var opacityGroup = dlg.add("group");
opacityGroup.add("statictext", undefined, "嵌入圖層 透明度 (%):");
var opacitySlider = opacityGroup.add("slider", undefined, 50, 0, 100);
opacitySlider.preferredSize.width = 200;
var opacityText = opacityGroup.add("edittext", undefined, "50");
opacityText.characters = 4;

opacitySlider.onChanging = function() {
    opacityText.text = Math.round(opacitySlider.value);
};
opacityText.onChange = function() {
    var val = parseInt(opacityText.text);
    if(!isNaN(val)) {
        if(val < 0) val = 0;
        if(val > 100) val = 100;
        opacitySlider.value = val;
        opacityText.text = val;
    }
};

var strokePanel = dlg.add("panel", undefined, "框外描邊設定");
strokePanel.alignChildren = ["left","top"];
var strokeEnableChk = strokePanel.add("checkbox", undefined, "啟用『框外』描邊");
strokeEnableChk.value = false;

var strokeSizeGrp = strokePanel.add("group");
strokeSizeGrp.add("statictext", undefined, "描邊大小(px):");
var strokeSizeSlider = strokeSizeGrp.add("slider", undefined, 3, 1, 30);
strokeSizeSlider.preferredSize.width = 150;
var strokeSizeText = strokeSizeGrp.add("edittext", undefined, "3");
strokeSizeText.characters = 3;

strokeSizeSlider.onChanging = function() {
    strokeSizeText.text = Math.round(strokeSizeSlider.value);
};
strokeSizeText.onChange = function() {
    var val = parseInt(strokeSizeText.text);
    if(!isNaN(val)) {
        if(val < 1) val = 1;
        if(val > 30) val = 30;
        strokeSizeSlider.value = val;
        strokeSizeText.text = val;
    }
};

var strokeColorGrp = strokePanel.add("group");
strokeColorGrp.add("statictext", undefined, "描邊顏色:");
var strokeColorBtn = strokeColorGrp.add("button", undefined, "選擇顏色");
var strokeColor = [255, 255, 55];

strokeColorBtn.onClick = function() {
    var c = $.colorPicker();
    if(c != -1) {
        strokeColor = [
            (c >> 16) & 0xFF,
            (c >> 8) & 0xFF,
            c & 0xFF
        ];
        strokeColorBtn.text = "R:" + strokeColor[0] + " G:" + strokeColor[1] + " B:" + strokeColor[2];
    }
};

dlg.add("statictext", undefined, "進度:");
var progressGrp = dlg.add("group");
var progressBar = progressGrp.add("progressbar", undefined, 0, 100);
progressBar.preferredSize.width = 300;
var progressText = progressGrp.add("statictext", undefined, "0 / 0");
progressText.preferredSize = { width: 60, height: progressText.preferredSize ? progressText.preferredSize.height : 20 };

var debugPanel = dlg.add("panel", undefined, "調試訊息");
debugPanel.alignChildren = ["fill", "top"];
var debugList = debugPanel.add("edittext", undefined, "", {multiline:true, readonly:true, scrollable:true});
debugList.preferredSize.height = 100;

var execBtn = dlg.add("button", undefined, "執行");

psdBtn.onClick = function() {
    try {
        var start = getPhotoshopCurrentFolder();
        var defaultFolder = psdPathText.text ? new Folder(psdPathText.text) : start;
        var folder = Folder.selectDialog("選擇PSD文件夾", defaultFolder);
        if(folder) {
            psdPathText.text = folder.fsName;
            debugLog('已選擇PSD文件夾: ' + folder.fsName);
        }
        updateMatchList();
    } catch (e) {
        debugLog('選擇PSD文件夾時出錯: ' + e.message);
        safeAlert('選擇PSD文件夾時出錯: ' + e.message);
    }
}

imgBtn.onClick = function() {
    try {
        var start = getPhotoshopCurrentFolder();
        var defaultFolder = imgPathText.text ? new Folder(imgPathText.text) : start;
        var folder = Folder.selectDialog("選擇原圖文件夾", defaultFolder);
        if(folder) {
            imgPathText.text = folder.fsName;
            debugLog('已選擇原圖文件夾: ' + folder.fsName);
        }
        updateMatchList();
    } catch (e) {
        debugLog('選擇原圖文件夾時出錯: ' + e.message);
        safeAlert('選擇原圖文件夾時出錯: ' + e.message);
    }
}

function getPhotoshopCurrentFolder() {
    var possibleFolders = [];
    try {
        if (app.documents.length > 0 && app.activeDocument && app.activeDocument.path) {
            possibleFolders.push(new Folder(app.activeDocument.path));
        }
    } catch (e) {
        debugLog('getPhotoshopCurrentFolder 方法1失敗: ' + e.message);
    }
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
    } catch (e) {
        debugLog('getPhotoshopCurrentFolder 方法2失敗: ' + e.message);
    }
    try {
        if (typeof getLastOpenedFolder === 'function') {
            var lastFolder = getLastOpenedFolder();
            if (lastFolder && lastFolder.exists) {
                possibleFolders.push(lastFolder);
            }
        }
    } catch (e) {
        debugLog('getPhotoshopCurrentFolder 方法3失敗: ' + e.message);
    }
    var commonFolders = [
        Folder.desktop,
        Folder.myPictures,
        new Folder(Folder.desktop.fsName + "/工作"),
        new Folder(Folder.desktop.fsName + "/projects")
    ];
    possibleFolders = possibleFolders.concat(commonFolders);
    for (var i = 0; i < possibleFolders.length; i++) {
        if (possibleFolders[i] && possibleFolders[i].exists) {
            debugLog('getPhotoshopCurrentFolder 返回: ' + possibleFolders[i].fsName);
            return possibleFolders[i];
        }
    }
    debugLog('getPhotoshopCurrentFolder 返回桌面');
    return Folder.desktop;
}

sortChk.onClick = updateMatchList;
reverseChk.onClick = updateMatchList;

function updateMatchList() {
    matchList.text = "";
    debugLog('更新匹配列表...');
    if(psdPathText.text != "" && imgPathText.text != "") {
        var psdFolder = new Folder(psdPathText.text);
        var imgFolder = new Folder(imgPathText.text);
        if (!psdFolder.exists) {
            debugLog('PSD文件夾不存在: ' + psdPathText.text);
            return;
        }
        if (!imgFolder.exists) {
            debugLog('原圖文件夾不存在: ' + imgPathText.text);
            return;
        }
        var psdFiles = psdFolder.getFiles("*.psd");
        var imgFiles = imgFolder.getFiles(/\.(jpg|jpeg|png|tif|tiff|bmp|gif|psb)$/i);
        debugLog('找到 PSD 文件: ' + psdFiles.length + ', 原圖文件: ' + imgFiles.length);
        if(sortChk.value) {
            psdFiles.sort();
            imgFiles.sort();
        }
        if (reverseChk && reverseChk.value) {
            try { psdFiles = psdFiles.reverse(); } catch (e) { debugLog('PSD倒序失敗: ' + e.message); }
            try { imgFiles = imgFiles.reverse(); } catch (e) { debugLog('原圖倒序失敗: ' + e.message); }
        }
        var len = Math.min(psdFiles.length, imgFiles.length);
        for(var i=0; i<len; i++) {
            matchList.text += psdFiles[i].name + " <=> " + imgFiles[i].name + "\r";
        }
    }
}

function padNumber(n, width) {
    var s = String(n);
    while (s.length < width) s = '0' + s;
    return s;
}
function formatProgress(curr, total) {
    var w = String(total).length;
    return padNumber(curr, w) + '/' + padNumber(total, w);
}

execBtn.onClick = function() {
    try {
        stopFlag = false;
        debugList.text = "";
        debugLog('開始執行批處理');

        var psdPath = trimString(safeGetText(psdPathText));
        var imgPath = trimString(safeGetText(imgPathText));
        if(psdPath == "" || imgPath == "") {
            safeAlert("請先選擇PSD文件夾和原圖文件夾！");
            debugLog('未選擇 PSD 或 原圖 文件夾');
            return;
        }

        var layerName = trimString(safeGetText(layerNameText));
        if(layerName == "") {
            safeAlert("圖層名字不能為空！");
            debugLog('圖層名字為空');
            return;
        }

        var psdFolder = new Folder(psdPath);
        var imgFolder = new Folder(imgPath);
        if (!psdFolder.exists) {
            safeAlert('PSD 文件夾不存在: ' + psdPath);
            debugLog('PSD文件夾不存在: ' + psdPath);
            return;
        }
        if (!imgFolder.exists) {
            safeAlert('原圖文件夾不存在: ' + imgPath);
            debugLog('原圖文件夾不存在: ' + imgPath);
            return;
        }

        var psdFiles = psdFolder.getFiles("*.psd");
        var imgFiles = imgFolder.getFiles(/\.(jpg|jpeg|png|tif|tiff|bmp|gif|psb)$/i);
        debugLog('執行時檢測 PSD 文件: ' + psdFiles.length + ', 原圖文件: ' + imgFiles.length);

        if(sortChk.value) {
            psdFiles.sort();
            imgFiles.sort();
        }
        if (reverseChk && reverseChk.value) {
            try { psdFiles = psdFiles.reverse(); } catch (e) { debugLog('PSD倒序失敗: ' + e.message); }
            try { imgFiles = imgFiles.reverse(); } catch (e) { debugLog('原圖倒序失敗: ' + e.message); }
        }

        var len = Math.min(psdFiles.length, imgFiles.length);
        if (len === 0) {
            safeAlert('未找到可處理的文件。請檢查PSD和原圖文件夾，並確保兩邊都有文件。');
            debugLog('未找到可處理的文件，len=0');
            return;
        }

        progressBar.maxvalue = len;
        progressBar.value = 0;
        progressText.text = formatProgress(0, len);

        for(var i=0; i<len; i++) {
            if(stopFlag) {
                safeAlert("批處理已手動中斷！已完成 " + i + " / " + len + " 文件。");
                debugLog('批處理手動中斷，已完成 ' + i + '/' + len);
                break;
            }

            var psdFile = psdFiles[i];
            var imgFile = imgFiles[i];
            debugLog('處理文件: ' + psdFile.name + ' 以及 ' + imgFile.name);
            var psdDoc = app.open(psdFile);
            var imgDoc = app.open(imgFile);

            var newLayer = imgDoc.activeLayer.duplicate(psdDoc, ElementPlacement.PLACEATBEGINNING);
            imgDoc.close(SaveOptions.DONOTSAVECHANGES);

            var layers = psdDoc.layers;
            if (layers.length > 1) {
                newLayer.move(layers[layers.length - 1], ElementPlacement.PLACEBEFORE);
            } else {
                newLayer.move(layers[0], ElementPlacement.PLACEAFTER);
            }
            newLayer.name = layerName;

            var docWidth = psdDoc.width.as("px");
            var docHeight = psdDoc.height.as("px");
            var layerWidth = newLayer.bounds[2].as("px") - newLayer.bounds[0].as("px");
            var layerHeight = newLayer.bounds[3].as("px") - newLayer.bounds[1].as("px");
            debugLog('文檔尺寸: ' + docWidth + 'x' + docHeight + ', 圖層尺寸: ' + layerWidth + 'x' + layerHeight);

            if(stretchFit.value) {
                var scale = Math.max(docWidth / layerWidth, docHeight / layerHeight) * 100;
                newLayer.resize(scale, scale, AnchorPosition.TOPLEFT);
                debugLog('使用保持比例填滿，縮放: ' + scale.toFixed(2) + '%');
            } else {
                var scaleX = (docWidth / layerWidth) * 100;
                var scaleY = (docHeight / layerHeight) * 100;
                newLayer.resize(scaleX, scaleY, AnchorPosition.TOPLEFT);
                debugLog('使用不保持比例拉伸，縮放X: ' + scaleX.toFixed(2) + '%, 縮放Y: ' + scaleY.toFixed(2) + '%');
            }

            newLayer.opacity = Math.round(opacitySlider.value);
            debugLog('設置透明度: ' + newLayer.opacity + '%');

            if (strokeEnableChk.value) {
                var targetLayer = findLayer(psdDoc, "框外");
                if (targetLayer) {
                    try {
                        app.activeDocument = psdDoc;
                        app.activeDocument.activeLayer = targetLayer;
                        var desc = new ActionDescriptor();
                        var ref = new ActionReference();
                        ref.putProperty(charIDToTypeID('Prpr'), stringIDToTypeID('layerEffects'));
                        ref.putEnumerated(charIDToTypeID('Lyr '), charIDToTypeID('Ordn'), charIDToTypeID('Trgt'));
                        desc.putReference(charIDToTypeID('null'), ref);
                        var effectsDesc = new ActionDescriptor();
                        var strokeDesc = new ActionDescriptor();
                        strokeDesc.putBoolean(stringIDToTypeID('enabled'), true);
                        strokeDesc.putUnitDouble(stringIDToTypeID('size'), charIDToTypeID('#Pxl'), parseInt(strokeSizeText.text, 10));
                        // 描邊位置必須用 style/outsetFrame（外描邊）。
                        // 用 position/outside 不會被 Photoshop 識別，會退回預設的「內描邊」。
                        // 對應 charID 寫法：putEnumerated('Styl', 'FStl', 'OutF')
                        strokeDesc.putEnumerated(stringIDToTypeID('style'), stringIDToTypeID('style'), stringIDToTypeID('outsetFrame'));
                        strokeDesc.putEnumerated(stringIDToTypeID('blendMode'), stringIDToTypeID('blendMode'), stringIDToTypeID('normal'));
                        strokeDesc.putUnitDouble(stringIDToTypeID('opacity'), charIDToTypeID('#Prc'), 100);
                        var colorDesc = new ActionDescriptor();
                        colorDesc.putDouble(charIDToTypeID('Rd  '), strokeColor[0]);
                        colorDesc.putDouble(charIDToTypeID('Grn '), strokeColor[1]);
                        colorDesc.putDouble(charIDToTypeID('Bl  '), strokeColor[2]);
                        strokeDesc.putObject(stringIDToTypeID('color'), stringIDToTypeID('RGBColor'), colorDesc);
                        effectsDesc.putObject(stringIDToTypeID('strokeStyle'), stringIDToTypeID('strokeStyle'), strokeDesc);
                        desc.putObject(charIDToTypeID('T   '), stringIDToTypeID('layerEffects'), effectsDesc);
                        executeAction(charIDToTypeID('setd'), desc, DialogModes.NO);
                        debugLog('已對「框外」圖層套用描邊');
                    } catch (e) {
                        debugLog('套用描邊時出錯: ' + e.message);
                        safeAlert('套用描邊時出錯: ' + e.message);
                    }
                } else {
                    debugLog('未找到名稱為「框外」的圖層');
                }
            }

            progressBar.value = i + 1;
            progressText.text = formatProgress(i + 1, len);
            dlg.update();
        }

        if(!stopFlag) {
            safeAlert("處理完成！");
            debugLog('處理完成');
        }
    } catch (e) {
        debugLog('執行過程中發生錯誤: ' + e.message);
        safeAlert('執行過程中發生錯誤: ' + e.message);
    }
}

function findLayer(doc, name) {
    function walk(layers) {
        for (var i = 0; i < layers.length; i++) {
            var L = layers[i];
            try {
                if (L.typename === "ArtLayer") {
                    if (L.name === name) return L;
                } else if (L.typename === "LayerSet") {
                    if (L.name === name) return L;
                    var found = walk(L.layers);
                    if (found) return found;
                }
            } catch (e) {
            }
        }
        return null;
    }
    return walk(doc.layers);
}

dlg.center();
dlg.show();
