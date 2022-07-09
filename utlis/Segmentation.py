"""
@file    :  Segmentation.py
@License :  (C)Copyright 2021 Haoran Jia, Fudan University. All Rights Reserved
@Contact :  21211140001@m.fudan.edu.cn
@Desc    :  用于处理分割图像

@Modify Time      @Author      @Version     
------------      -------      --------     
2022/7/8 15:41   JHR          1.0         
"""

import os
import filetype
from tqdm import tqdm

import cv2
import pydicom
import SimpleITK as sitk

import matplotlib.pyplot as plt
import numpy as np


class SegmentBase(object):
    def __init__(self):
        self.img = None  # 原始CT图像
        self.seg = None  # 完整分割结果

    def ReadOriginImage(self, fpath):
        """
        利用sitk读取原始CT文件，nii等格式
        :param fpath: CT文件路径
        :return: 读取的CT文件
        """
        self.img = sitk.ReadImage(fpath)
        return self.img

    def ReadOriginImageSeries(self, folder):
        """
        利用sitk读取原始CT文件，DCM序列文件
        :param folder: CT文件夹路径
        :return: 读取的CT文件
        """
        reader = sitk.ImageSeriesReader()
        ID = reader.GetGDCMSeriesIDs(folder)
        assert len(ID) == 1, "No Series or more than one series in specified folder."
        fnames = reader.GetGDCMSeriesFileNames(directory=folder, seriesID=ID[0])
        reader.SetFileNames(fnames)
        self.img = reader.Execute()
        return self.img


class SegmentFormatConverter(SegmentBase):
    def __init__(self):
        super().__init__()


class Jpg2niiConverter(SegmentFormatConverter):
    def __init__(self):
        super().__init__()

    @staticmethod
    def GetImageLayerByName(fname):
        z = int(fname[-8:-4])
        return z

    def OrganConvert(self, folder_jpg, fpath_save, GetImageLayerMethod=None, threshold=128):
        """
        将单独器官的一组jpg保存为单独的器官nii
        :param folder_jpg: 读取jpg的文件夹
        :param fpath_save: 保存nii的路径
        :param GetImageLayerMethod: 获取jpg层信息的方法
        :param threshold: 对jpg进行二值化的阈值
        :return: 生成的nii文件
        """
        # 设置缺省值
        if GetImageLayerMethod is None:
            GetImageLayerMethod = self.GetImageLayerByName
        # 根据原始图像生成空白背景
        seg = np.zeros_like(sitk.GetArrayViewFromImage(self.img))
        # 对每一张jpg进行处理，得到完整的CT图
        for fname in os.listdir(folder_jpg):
            fpath = os.path.join(folder_jpg, fname)
            kind = filetype.guess(fpath)  # 检验是否全部为jpg文件
            assert kind.extension == 'jpg', "Wrong type in specified folder."
            seg_slice = cv2.imread(filename=fpath, flags=0)  # 读取文件为灰度图
            z = GetImageLayerMethod(fname)  # 获取对应的层数
            seg[z] = seg_slice

        # jpg图片读取后有非0或255的数，需要处理, 以250为界限
        seg[seg > threshold] = 255
        seg[seg <= threshold] = 0

        # 转换为Image
        seg = sitk.GetImageFromArray(np.flip(seg))  # 输出需要完全翻转才能跟dcm一致
        seg.CopyInformation(self.img)
        seg = sitk.Cast(image=seg, pixelID=sitk.sitkUInt8)
        # 创建保存所有器官分割结果的文件夹
        folder_save = os.path.dirname(fpath_save)
        if not os.path.exists(folder_save):
            os.mkdir(folder_save)
        # 保存文件
        sitk.WriteImage(image=seg, fileName=fpath_save)
        return seg


class SegmentAssembleImageFilter(SegmentBase):
    OrganID = {
        # 有重叠部分, 先写大体积的，然后往上覆盖
        "Outline": 10, "Body": 10,
        "Skin": 11, "Muscle": 13,
        "Bone": 46, "Skeleton": 46, "Marrow": 47,
        "SCord": 65, "SpinalCore": 65, "Brain": 18, "Eyes": 22,
        "Lung": 33, "Heart": 26, "Breast": 19,

        "Intestine": 44, "Liver": 32, "Kidney": 28, "Stomach": 67,
        "ParotidGland": 43,

        "Bladder": 15, "Ovary": 86, "Spleen": 66, "Thyroid": 70,
        "Pancrease": 38, "GallBladder": 24,
    }

    def __init__(self, folder_organs=None, fpath_save=None):
        super().__init__()
        self.folder_organs = folder_organs
        self.fpath_save = fpath_save

    def SetFolderOrgans(self, folder):
        self.folder_organs = folder

    def AnalyseOverlap(self, stop_organ_list=None):
        # 缺省值
        if stop_organ_list is None:
            stop_organ_list = []
        # 获取全部器官list，去除缺省值
        organs = os.listdir(self.folder_organs)
        organs = [organ for organ in organs if organ not in stop_organ_list]
        # 对器官进行循环比较，输出重叠较大的器官
        for i in range(len(organs)):
            for j in range(i + 1, len(organs)):
                # 器官名称
                organ_i = organs[i][0:-4]
                organ_j = organs[j][0:-4]
                # 读取器官图像
                img_i = sitk.GetArrayFromImage(sitk.ReadImage(os.path.join(self.folder_organs, organs[i]))).astype(bool)
                img_j = sitk.GetArrayFromImage(sitk.ReadImage(os.path.join(self.folder_organs, organs[j]))).astype(bool)
                # 计算器官体积点数
                n_i = np.sum(img_i)
                n_j = np.sum(img_j)
                # 分析重合情况
                overlap = np.sum(img_i * img_j)
                percent_i = (overlap / n_i * 100).round(decimals=1)
                percent_j = (overlap / n_j * 100).round(decimals=1)
                ratio = (n_i / n_j).round(2)
                if overlap != 0 and (percent_i >= 1 or percent_j >= 1):
                    print(f"Overlap Points: {overlap} ({percent_i}%, {percent_j}%)", end="\t\t\t")
                    print(f"{organ_i}: {n_i};\t{organ_j}: {n_j};\t{ratio}")
        return 0

    def Execute(self, fpath_save=None):
        # 检查保存路径是否正确
        if fpath_save is None:
            fpath_save = self.fpath_save
        assert fpath_save is not None, "Save path is not specified."

        # 判断OrganID中是否有遗漏的器官
        fnames_miss = [fname for fname in os.listdir(self.folder_organs)
                       if fname[0:-4] not in SegmentAssembleImageFilter.OrganID]
        assert len(fnames_miss) == 0, "Missed organ in OrganID."

        # 根据原图像生成空白分割背景
        seg = np.zeros_like(sitk.GetArrayViewFromImage(self.img)).astype(np.uint8)
        seg_bool = seg.astype(bool)

        # 按照顺序对OrganID中的器官进行覆写
        pbar = tqdm(SegmentAssembleImageFilter.OrganID)
        for organ_name in pbar:  # 对字典中的器官名进行循环
            fname = organ_name + ".nii"
            # 在文件夹中寻找器官
            if fname in os.listdir(self.folder_organs):
                pbar.set_description(desc=organ_name)
                # 读取器官为数组，转换bool值
                organ = sitk.GetArrayFromImage(sitk.ReadImage(os.path.join(self.folder_organs, fname)))
                organ_bool = organ.astype(bool)
                # 算差集, 将新器官添加到seg中
                seg_minus_organ = seg_bool ^ (seg_bool & organ_bool)
                seg = seg * seg_minus_organ + organ_bool * SegmentAssembleImageFilter.OrganID[organ_name]
                seg_bool = seg.astype(bool)
        pbar.close()

        seg = sitk.GetImageFromArray(seg)
        seg.CopyInformation(self.img)
        seg = sitk.Cast(seg, sitk.sitkUInt8)
        sitk.WriteImage(seg, fpath_save)
        return seg


class SegmentSplitImageFilter(SegmentBase):
    StandardName = {
        10: 'Body', 11: 'Skin', 13: 'Muscle', 15: 'Bladder', 18: 'Brain',
        19: 'Breast', 21: 'Esophagus', 22: 'Eye', 23: 'Len', 24: 'GallBladder',
        26: 'Heart', 28: 'Kidney', 29: 'Larynx', 32: 'Liver', 33: 'Lung',
        37: 'OralCavity', 38: 'Pancreas', 42: 'Pituitary', 43: 'Parotid', 44: 'Intestine',
        46: 'Bone', 47: 'Marrow', 63: 'TMJ', 65: 'SpinalCord', 66: 'Spleen',
        67: 'Stomach', 70: 'Thyroid', 73: 'Trachea', 75: 'Cochlea', 76: 'BrainStem',
        77: 'TemporalLobe', 78: 'OpticChiasm', 79: 'OpticalNerve', 80: 'Rectum', 81: 'Sigmoid',
        82: 'Duodenum', 86: 'Ovary'
    }
    MultipleOrgans = {
        10: (10, 11), 22: (22, 23), 18: (18, 76, 77), 46: (46, 47),
    }

    def __init__(self, fpath_seg=None, folder_save=None):
        super().__init__()
        self.fpath_seg = fpath_seg
        self.folder_save = folder_save

    def SetFpathSeg(self, fpath):
        self.fpath_seg = fpath

    @staticmethod
    def _AssembleMultipleOrgans(seg, ID_main):
        # 创建一个空白的背景
        seg_organ_main = np.zeros_like(seg)
        for ID in SegmentSplitImageFilter.MultipleOrgans[ID_main]:
            # 提取各器官，然后加到总分割图中
            seg_organ = np.copy(seg)
            seg_organ[seg != ID] = 0
            seg_organ[seg == ID] = 255
            seg_organ_main += seg_organ
        return seg_organ_main

    def Execute(self, folder_save=None):
        if folder_save is None:
            folder_save = self.folder_save
        assert folder_save is not None, "folder to save is not specified."
        if not os.path.exists(folder_save):
            os.makedirs(folder_save)

        # 读取全器官文件
        seg_img = sitk.ReadImage(self.fpath_seg)        # Image，用于拷贝信息
        seg = sitk.GetArrayFromImage(seg_img)       # ndarray，用于运算
        # 对器官ID值进行循环，保存单独器官
        pbar = tqdm(SegmentSplitImageFilter.StandardName)
        for ID in pbar:
            if ID in seg:
                pbar.set_description(str(SegmentSplitImageFilter.StandardName[ID]))
                if ID in SegmentSplitImageFilter.MultipleOrgans:
                    seg_organ = self._AssembleMultipleOrgans(seg, ID)
                else:
                    seg_organ = np.copy(seg)
                    seg_organ[seg != ID] = 0
                    seg_organ[seg == ID] = 255

                seg_organ = sitk.GetImageFromArray(seg_organ)
                seg_organ.CopyInformation(seg_img)
                seg_organ = sitk.Cast(seg_organ, sitk.sitkUInt8)

                fpath = os.path.join(folder_save, str(ID)+'_'+SegmentSplitImageFilter.StandardName[ID]+".nii")
                sitk.WriteImage(seg_organ, fpath)
        pbar.close()



