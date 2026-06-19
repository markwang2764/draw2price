"""
导出服务 - 生成PDF格式的可下载文档
"""
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

class ExportService:
    def __init__(self):
        self.export_dir = Path("exports")
        self.export_dir.mkdir(exist_ok=True)
        self._register_fonts()
        self._init_styles()
    
    def _register_fonts(self):
        """注册中文字体"""
        # macOS 系统字体路径
        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc", 
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
        
        registered = False
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('Chinese', font_path))
                    registered = True
                    break
                except:
                    continue
        
        if not registered:
            # 使用默认字体
            self.font_name = 'Helvetica'
        else:
            self.font_name = 'Chinese'
    
    def _init_styles(self):
        """初始化样式"""
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(
            name='ChineseTitle',
            fontName=self.font_name,
            fontSize=18,
            alignment=1,
            spaceAfter=20
        ))
        self.styles.add(ParagraphStyle(
            name='ChineseHeading',
            fontName=self.font_name,
            fontSize=14,
            spaceBefore=15,
            spaceAfter=10
        ))
        self.styles.add(ParagraphStyle(
            name='ChineseNormal',
            fontName=self.font_name,
            fontSize=10,
            leading=14
        ))
    
    def export_gcode(self, gcode_data: Dict, analysis_id: str) -> str:
        """导出G代码文件"""
        filename = f"GCODE_{analysis_id}_{gcode_data.get('program_number', 'O0001')}.nc"
        filepath = self.export_dir / filename
        
        content = self._format_gcode(gcode_data)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return str(filepath)
    
    def export_all_gcode(self, gcode_programs: list, analysis_id: str) -> str:
        """导出所有G代码到一个文件"""
        filename = f"GCODE_ALL_{analysis_id}.nc"
        filepath = self.export_dir / filename
        
        content_parts = []
        for i, gcode in enumerate(gcode_programs, 1):
            content_parts.append(f"(========== 工序 {i} ==========)")
            content_parts.append(self._format_gcode(gcode))
            content_parts.append("")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(content_parts))
        
        return str(filepath)
    
    def _format_gcode(self, gcode_data: Dict) -> str:
        """格式化G代码"""
        template = """%
{program_number}
(==================================================)
(  程序名称: {part_name})
(  设备: {equipment})
(  生成时间: {timestamp})
(==================================================)
(
(  刀具列表:
{tool_list}
(
(  装夹说明:
(  {setup_notes}
(
(==================================================)

{code}

M30
%
"""
        tool_list_str = ""
        for tool in gcode_data.get("tool_list", []):
            tool_list_str += f"(    {tool.get('tool_number', 'T01')} - {tool.get('tool_name', '刀具')}\n"
        
        return template.format(
            program_number=gcode_data.get("program_number", "O0001"),
            part_name=gcode_data.get("part_name", "未命名零件"),
            equipment=gcode_data.get("equipment", "未知设备"),
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            tool_list=tool_list_str,
            setup_notes=gcode_data.get("setup_notes", "无").replace('\n', '\n(  '),
            code=gcode_data.get("code", "")
        )
    
    def export_schedule(self, schedule_data: Dict, analysis_id: str) -> str:
        """导出排产计划(PDF格式)"""
        filename = f"SCHEDULE_{analysis_id}.pdf"
        filepath = self.export_dir / filename
        
        doc = SimpleDocTemplate(str(filepath), pagesize=A4, 
                               leftMargin=20*mm, rightMargin=20*mm,
                               topMargin=20*mm, bottomMargin=20*mm)
        elements = []
        
        # 标题
        elements.append(Paragraph("排产计划报表", self.styles['ChineseTitle']))
        elements.append(Spacer(1, 10))
        
        # 基本信息表格
        info_data = [
            ["生成时间", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "零件名称", schedule_data.get('part_name', '-')],
            ["生产数量", f"{schedule_data.get('quantity', 0)} 件", "优先级", schedule_data.get('priority', '-')],
            ["开始日期", schedule_data.get('start_date', '-'), "交货日期", schedule_data.get('due_date', '-')],
            ["总工时", f"{schedule_data.get('total_hours', 0)} 小时", "设备利用率", f"{schedule_data.get('utilization_rate', 0)*100:.1f}%"],
        ]
        
        info_table = Table(info_data, colWidths=[70, 120, 70, 120])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('BACKGROUND', (2, 0), (2, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 20))
        
        # 任务列表标题
        elements.append(Paragraph("任务明细", self.styles['ChineseHeading']))
        
        # 任务表格
        task_header = ["序号", "工序名称", "设备", "操作员", "开始时间", "时长(分)"]
        task_data = [task_header]
        
        for i, task in enumerate(schedule_data.get("tasks", []), 1):
            task_data.append([
                str(i),
                task.get("process_name", "-"),
                task.get("equipment_name", "-"),
                task.get("operator_name", "-"),
                task.get("start_time", "-")[:16] if task.get("start_time") else "-",
                str(task.get("duration_minutes", 0))
            ])
        
        if len(task_data) > 1:
            task_table = Table(task_data, colWidths=[30, 100, 80, 60, 100, 50])
            task_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), self.font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.2, 0.4, 0.6)),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.95, 0.95)]),
            ]))
            elements.append(task_table)
        
        doc.build(elements)
        return str(filepath)
    
    def export_quotation(self, quotation_data: Dict, analysis_id: str) -> str:
        """导出报价单(PDF格式)"""
        filename = f"QUOTATION_{analysis_id}.pdf"
        filepath = self.export_dir / filename
        
        doc = SimpleDocTemplate(str(filepath), pagesize=A4,
                               leftMargin=20*mm, rightMargin=20*mm,
                               topMargin=20*mm, bottomMargin=20*mm)
        elements = []
        
        # 标题
        elements.append(Paragraph("报 价 单", self.styles['ChineseTitle']))
        elements.append(Paragraph("QUOTATION", ParagraphStyle(
            name='SubTitle', fontName=self.font_name, fontSize=12, alignment=1, spaceAfter=20
        )))
        
        # 基本信息
        info_data = [
            ["报价单号", quotation_data.get('quotation_number', '-'), "日期", quotation_data.get('date', '-')],
            ["客户", quotation_data.get('customer', '待定'), "有效期至", quotation_data.get('valid_until', '-')],
            ["零件名称", quotation_data.get('part_name', '-'), "数量", f"{quotation_data.get('quantity', 0)} 件"],
        ]
        
        info_table = Table(info_data, colWidths=[70, 130, 70, 130])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('BACKGROUND', (2, 0), (2, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 20))
        
        # 费用明细
        elements.append(Paragraph("费用明细", self.styles['ChineseHeading']))
        
        items_header = ["序号", "项目描述", "数量", "单位", "单价(元)", "金额(元)"]
        items_data = [items_header]
        
        for item in quotation_data.get("items", []):
            items_data.append([
                str(item.get('item', '')),
                item.get('description', '-'),
                str(item.get('quantity', 0)),
                item.get('unit', '-'),
                f"{item.get('unit_price', 0):.2f}",
                f"{item.get('total_price', 0):.2f}"
            ])
        
        # 如果没有明细，添加汇总行
        if len(items_data) == 1:
            items_data.append(["1", "材料费", "1", "批", f"{quotation_data.get('material_cost', 0):.2f}", f"{quotation_data.get('material_cost', 0):.2f}"])
            items_data.append(["2", "加工费", "1", "批", f"{quotation_data.get('processing_cost', 0):.2f}", f"{quotation_data.get('processing_cost', 0):.2f}"])
            items_data.append(["3", "设备费", "1", "批", f"{quotation_data.get('equipment_cost', 0):.2f}", f"{quotation_data.get('equipment_cost', 0):.2f}"])
            items_data.append(["4", "人工费", "1", "批", f"{quotation_data.get('labor_cost', 0):.2f}", f"{quotation_data.get('labor_cost', 0):.2f}"])
        
        items_table = Table(items_data, colWidths=[30, 150, 50, 40, 70, 70])
        items_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.2, 0.4, 0.6)),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 15))
        
        # 汇总
        subtotal = quotation_data.get('subtotal', 0)
        overhead = quotation_data.get('overhead', 0)
        profit = quotation_data.get('profit', 0)
        total = quotation_data.get('total', 0)
        
        summary_data = [
            ["", "", "", "", "小计", f"¥ {subtotal:.2f}"],
            ["", "", "", "", f"管理费({quotation_data.get('overhead_rate', 0.15)*100:.0f}%)", f"¥ {overhead:.2f}"],
            ["", "", "", "", f"利润({quotation_data.get('profit_rate', 0.2)*100:.0f}%)", f"¥ {profit:.2f}"],
            ["", "", "", "", "总计", f"¥ {total:.2f}"],
        ]
        
        summary_table = Table(summary_data, colWidths=[30, 150, 50, 40, 70, 70])
        summary_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
            ('ALIGN', (5, 0), (5, -1), 'RIGHT'),
            ('FONTSIZE', (-1, -1), (-1, -1), 14),
            ('TEXTCOLOR', (-1, -1), (-1, -1), colors.red),
            ('LINEABOVE', (4, -1), (-1, -1), 1, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 30))
        
        # 备注
        elements.append(Paragraph("备注说明:", self.styles['ChineseHeading']))
        elements.append(Paragraph(quotation_data.get('notes', '无'), self.styles['ChineseNormal']))
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("1. 本报价单有效期为30天", self.styles['ChineseNormal']))
        elements.append(Paragraph("2. 付款方式：预付50%，交货前付清余款", self.styles['ChineseNormal']))
        elements.append(Paragraph("3. 交货周期：根据排产计划确定", self.styles['ChineseNormal']))
        elements.append(Spacer(1, 40))
        
        # 签名栏
        sign_data = [["报价人：____________", "审核人：____________", "客户确认：____________"]]
        sign_table = Table(sign_data, colWidths=[140, 140, 140])
        sign_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        elements.append(sign_table)
        
        doc.build(elements)
        return str(filepath)
    
    def _export_quotation_html(self, quotation_data: Dict, analysis_id: str) -> str:
        """导出报价单(HTML格式备用)"""
        filename = f"QUOTATION_{analysis_id}.html"
        filepath = self.export_dir / filename
        
        template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>报价单 - {quotation_number}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: "Microsoft YaHei", "SimSun", sans-serif; padding: 40px; background: #f5f5f5; }}
        .quotation {{ max-width: 800px; margin: 0 auto; background: white; padding: 40px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ text-align: center; border-bottom: 3px double #333; padding-bottom: 20px; margin-bottom: 30px; }}
        .header h1 {{ font-size: 28px; color: #333; margin-bottom: 10px; }}
        .header .company {{ font-size: 14px; color: #666; }}
        .info-row {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
        .info-item {{ font-size: 14px; }}
        .info-item label {{ color: #666; }}
        .info-item span {{ color: #333; font-weight: bold; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background: #f8f8f8; font-weight: bold; }}
        .text-right {{ text-align: right; }}
        .text-center {{ text-align: center; }}
        .summary {{ margin-top: 20px; }}
        .summary-row {{ display: flex; justify-content: flex-end; padding: 8px 0; }}
        .summary-label {{ width: 150px; text-align: right; padding-right: 20px; }}
        .summary-value {{ width: 120px; text-align: right; font-weight: bold; }}
        .total-row {{ font-size: 18px; color: #d32f2f; border-top: 2px solid #333; padding-top: 15px; margin-top: 15px; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; }}
        .footer-row {{ display: flex; justify-content: space-between; margin-top: 30px; }}
        .signature {{ width: 200px; text-align: center; }}
        .signature-line {{ border-bottom: 1px solid #333; height: 40px; margin-bottom: 5px; }}
        .notes {{ margin-top: 20px; padding: 15px; background: #f9f9f9; border-radius: 5px; }}
        .notes h4 {{ margin-bottom: 10px; }}
        @media print {{
            body {{ padding: 0; background: white; }}
            .quotation {{ box-shadow: none; }}
        }}
    </style>
</head>
<body>
    <div class="quotation">
        <div class="header">
            <h1>报 价 单</h1>
            <p class="company">QUOTATION</p>
        </div>
        
        <div class="info-row">
            <div class="info-item">
                <label>报价单号：</label>
                <span>{quotation_number}</span>
            </div>
            <div class="info-item">
                <label>日期：</label>
                <span>{date}</span>
            </div>
            <div class="info-item">
                <label>有效期至：</label>
                <span>{valid_until}</span>
            </div>
        </div>
        
        <div class="info-row">
            <div class="info-item">
                <label>客户：</label>
                <span>{customer}</span>
            </div>
            <div class="info-item">
                <label>零件名称：</label>
                <span>{part_name}</span>
            </div>
            <div class="info-item">
                <label>数量：</label>
                <span>{quantity} 件</span>
            </div>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th class="text-center" style="width:50px">序号</th>
                    <th>项目描述</th>
                    <th class="text-right" style="width:80px">数量</th>
                    <th class="text-center" style="width:60px">单位</th>
                    <th class="text-right" style="width:100px">单价(元)</th>
                    <th class="text-right" style="width:100px">金额(元)</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>
        
        <div class="summary">
            <div class="summary-row">
                <span class="summary-label">小计：</span>
                <span class="summary-value">¥ {subtotal}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">管理费({overhead_rate}%)：</span>
                <span class="summary-value">¥ {overhead}</span>
            </div>
            <div class="summary-row">
                <span class="summary-label">利润({profit_rate}%)：</span>
                <span class="summary-value">¥ {profit}</span>
            </div>
            <div class="summary-row total-row">
                <span class="summary-label">总计：</span>
                <span class="summary-value">¥ {total}</span>
            </div>
        </div>
        
        <div class="notes">
            <h4>备注说明：</h4>
            <p>{notes}</p>
        </div>
        
        <div class="footer">
            <p>1. 本报价单有效期为30天</p>
            <p>2. 付款方式：预付50%，交货前付清余款</p>
            <p>3. 交货周期：根据排产计划确定</p>
            
            <div class="footer-row">
                <div class="signature">
                    <div class="signature-line"></div>
                    <p>报价人</p>
                </div>
                <div class="signature">
                    <div class="signature-line"></div>
                    <p>审核人</p>
                </div>
                <div class="signature">
                    <div class="signature-line"></div>
                    <p>客户确认</p>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
        
        # 生成项目行HTML
        items_html = ""
        for item in quotation_data.get("items", []):
            items_html += f"""<tr>
                <td class="text-center">{item.get('item', '')}</td>
                <td>{item.get('description', '')}</td>
                <td class="text-right">{item.get('quantity', 0)}</td>
                <td class="text-center">{item.get('unit', '')}</td>
                <td class="text-right">{item.get('unit_price', 0):.2f}</td>
                <td class="text-right">{item.get('total_price', 0):.2f}</td>
            </tr>"""
        
        content = template.format(
            quotation_number=quotation_data.get("quotation_number", ""),
            date=quotation_data.get("date", ""),
            valid_until=quotation_data.get("valid_until", ""),
            customer=quotation_data.get("customer", "待定"),
            part_name=quotation_data.get("part_name", ""),
            quantity=quotation_data.get("quantity", 0),
            items_html=items_html,
            subtotal=f"{quotation_data.get('subtotal', 0):.2f}",
            overhead_rate=f"{quotation_data.get('overhead_rate', 0.15)*100:.0f}",
            overhead=f"{quotation_data.get('overhead', 0):.2f}",
            profit_rate=f"{quotation_data.get('profit_rate', 0.2)*100:.0f}",
            profit=f"{quotation_data.get('profit', 0):.2f}",
            total=f"{quotation_data.get('total', 0):.2f}",
            notes=quotation_data.get("notes", "无")
        )
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return str(filepath)
    
    def export_process_card(self, process_plan: Dict, part_analysis: Dict, analysis_id: str) -> str:
        """导出工艺卡(PDF格式)"""
        filename = f"PROCESS_CARD_{analysis_id}.pdf"
        filepath = self.export_dir / filename
        
        doc = SimpleDocTemplate(str(filepath), pagesize=A4,
                               leftMargin=15*mm, rightMargin=15*mm,
                               topMargin=15*mm, bottomMargin=15*mm)
        elements = []
        
        # 标题
        elements.append(Paragraph("机械加工工艺卡", self.styles['ChineseTitle']))
        elements.append(Spacer(1, 10))
        
        # 材料信息
        material = part_analysis.get("material", {})
        if isinstance(material, dict):
            material_str = f"{material.get('name', '')} {material.get('grade', '')}"
        else:
            material_str = str(material)
        
        # 毛坯尺寸
        blank_dims = process_plan.get("blank_dimensions", {})
        blank_dims_str = f"{blank_dims.get('length', '-')}x{blank_dims.get('width', '-')}x{blank_dims.get('height', '-')}mm"
        
        # 基本信息
        info_data = [
            ["零件名称", part_analysis.get('part_name', '-'), "零件编号", part_analysis.get('part_number', '-'), "日期", datetime.now().strftime('%Y-%m-%d')],
            ["材料", material_str, "毛坯类型", process_plan.get('blank_type', '-'), "总工时", f"{process_plan.get('total_time_minutes', 0)}分"],
            ["毛坯尺寸", blank_dims_str, "复杂程度", part_analysis.get('complexity_level', '-'), "", ""],
        ]
        
        info_table = Table(info_data, colWidths=[55, 85, 55, 75, 45, 60])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('BACKGROUND', (2, 0), (2, -1), colors.lightgrey),
            ('BACKGROUND', (4, 0), (4, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 15))
        
        # 零件特征
        elements.append(Paragraph("零件特征", self.styles['ChineseHeading']))
        
        features = part_analysis.get("features", [])
        if features:
            feat_data = [["特征名称", "类型", "尺寸", "公差", "粗糙度"]]
            for feat in features[:6]:  # 最多显示6个特征
                dims = feat.get("dimensions", {})
                dims_str = ", ".join([f"{k}:{v}" for k, v in dims.items()])[:30]
                feat_data.append([
                    feat.get('name', '-')[:15],
                    feat.get('type', '-'),
                    dims_str or '-',
                    feat.get('tolerance', '-'),
                    feat.get('surface_finish', '-')
                ])
            
            feat_table = Table(feat_data, colWidths=[80, 60, 120, 50, 50])
            feat_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), self.font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.3, 0.5, 0.3)),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(feat_table)
        elements.append(Spacer(1, 15))
        
        # 工序列表
        elements.append(Paragraph("工序列表", self.styles['ChineseHeading']))
        
        steps = process_plan.get("steps", [])
        if steps:
            step_data = [["工序", "工序名称", "工序内容", "设备", "工时(分)", "刀具"]]
            for step in steps:
                tools = ", ".join(step.get("tools_required", []))[:20] or "-"
                desc = step.get('description', '-')[:40]
                step_data.append([
                    str(step.get('step_number', '')),
                    step.get('process_name', '-')[:12],
                    desc,
                    step.get('equipment_type', '-')[:12],
                    str(step.get('estimated_time_minutes', 0)),
                    tools
                ])
            
            step_table = Table(step_data, colWidths=[30, 65, 140, 65, 40, 70])
            step_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), self.font_name),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.2, 0.4, 0.6)),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (4, 0), (4, -1), 'CENTER'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.95, 0.95)]),
            ]))
            elements.append(step_table)
        elements.append(Spacer(1, 15))
        
        # 特殊要求
        elements.append(Paragraph("特殊要求", self.styles['ChineseHeading']))
        elements.append(Paragraph(process_plan.get('special_requirements', '无'), self.styles['ChineseNormal']))
        elements.append(Spacer(1, 30))
        
        # 签名栏
        sign_data = [["编制：____________", "审核：____________", "批准：____________"]]
        sign_table = Table(sign_data, colWidths=[130, 130, 130])
        sign_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
        ]))
        elements.append(sign_table)
        
        doc.build(elements)
        return str(filepath)
    
    def _export_process_card_html(self, process_plan: Dict, part_analysis: Dict, analysis_id: str) -> str:
        """导出工艺卡(HTML格式备用)"""
        filename = f"PROCESS_CARD_{analysis_id}.html"
        filepath = self.export_dir / filename
        
        # 保留原HTML模板作为备用
        template = """<html><body><h1>工艺卡</h1></body></html>"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(template)
        return str(filepath)
    
    def export_full_report(self, analysis_result: Dict) -> Dict[str, str]:
        """导出完整报告（所有文档）"""
        analysis_id = analysis_result.get("id", "UNKNOWN")
        
        files = {}
        
        # 导出G代码
        if analysis_result.get("gcode_programs"):
            files["gcode"] = self.export_all_gcode(
                analysis_result["gcode_programs"], 
                analysis_id
            )
        
        # 导出排产计划
        if analysis_result.get("production_schedule"):
            files["schedule"] = self.export_schedule(
                analysis_result["production_schedule"],
                analysis_id
            )
        
        # 导出报价单
        if analysis_result.get("quotation"):
            files["quotation"] = self.export_quotation(
                analysis_result["quotation"],
                analysis_id
            )
        
        # 导出工艺卡
        if analysis_result.get("process_plan") and analysis_result.get("part_analysis"):
            files["process_card"] = self.export_process_card(
                analysis_result["process_plan"],
                analysis_result["part_analysis"],
                analysis_id
            )
        
        return files

export_service = ExportService()
