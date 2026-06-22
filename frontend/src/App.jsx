import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';
import {
  Upload,
  FileText,
  Settings,
  Play,
  Download,
  CheckCircle,
  Clock,
  AlertCircle,
  Loader2,
  ChevronRight,
  Factory,
  Cpu,
  Calendar,
  DollarSign,
  Code,
  FileSpreadsheet,
  Printer,
  BookOpen,
  Eye,
  X,
  Package,
  Activity,
  Zap,
  Wrench,
  Users,
  Plus,
  Trash2,
  ShieldCheck,
} from 'lucide-react';
import KnowledgeManager from './KnowledgeManager';

// API 基础URL
const API_BASE = '/api';

function App() {
  const [activeTab, setActiveTab] = useState('analysis');
  const [file, setFile] = useState(null);
  const [description, setDescription] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [priority, setPriority] = useState('normal');
  const [dueDate, setDueDate] = useState('');
  const [customer, setCustomer] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [resources, setResources] = useState(null);
  const [thinkingLogs, setThinkingLogs] = useState([]);
  const thinkingRef = useRef(null);
  const [previewModal, setPreviewModal] = useState({ open: false, type: '', url: '', title: '' });

  // 文件拖放处理
  const onDrop = useCallback(acceptedFiles => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      setError(null);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'image/*': ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'],
      'application/pdf': ['.pdf'],
    },
    maxFiles: 1,
  });

  // 自动滚动到最新思考内容
  useEffect(() => {
    if (thinkingRef.current) {
      thinkingRef.current.scrollTop = thinkingRef.current.scrollHeight;
    }
  }, [thinkingLogs]);

  // 执行流式分析
  const runFullAnalysis = async () => {
    if (!file && !description.trim()) {
      setError('请上传图纸文件或输入零件描述');
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);
    setCurrentStep(0);
    setThinkingLogs([]);

    try {
      const formData = new FormData();
      if (file) {
        formData.append('file', file);
      }
      if (description.trim()) {
        formData.append('description', description);
      }
      formData.append('quantity', quantity);
      formData.append('priority', priority);
      if (dueDate) formData.append('due_date', dueDate);
      if (customer) formData.append('customer', customer);

      // 使用流式API
      const timestamp = () => new Date().toLocaleTimeString();
      setThinkingLogs(prev => [
        ...prev,
        {
          type: 'debug',
          content: `[${timestamp()}] 🌐 发起请求: ${API_BASE}/analysis/stream/v2 (编排)`,
          timestamp: timestamp(),
        },
      ]);

      const response = await fetch(`${API_BASE}/analysis/stream/v2`, {
        method: 'POST',
        body: formData,
      });

      setThinkingLogs(prev => [
        ...prev,
        {
          type: 'debug',
          content: `[${timestamp()}] 📡 响应状态: ${response.status} ${response.statusText}`,
          timestamp: timestamp(),
        },
      ]);

      if (!response.ok) {
        const errorText = await response.text();
        setThinkingLogs(prev => [
          ...prev,
          {
            type: 'error',
            content: `[${timestamp()}] ❌ HTTP错误: ${response.status} - ${errorText}`,
            timestamp: timestamp(),
          },
        ]);
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let chunkCount = 0;
      let buffer = ''; // 缓冲区用于处理被截断的JSON

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          setThinkingLogs(prev => [
            ...prev,
            {
              type: 'debug',
              content: `[${timestamp()}] ✅ 流式传输完成，共接收 ${chunkCount} 个数据块`,
              timestamp: timestamp(),
            },
          ]);
          break;
        }

        chunkCount++;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');

        // 保留最后一行（可能不完整）到缓冲区
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              handleStreamEvent(data);
            } catch (e) {
              console.error('Parse error:', e);
              setThinkingLogs(prev => [
                ...prev,
                {
                  type: 'error',
                  content: `[${timestamp()}] ⚠️ 解析错误: ${e.message} - 数据长度: ${line.length}`,
                  timestamp: timestamp(),
                },
              ]);
            }
          }
        }
      }

      // 处理缓冲区中剩余的数据
      if (buffer.trim() && buffer.startsWith('data: ')) {
        try {
          const data = JSON.parse(buffer.slice(6));
          handleStreamEvent(data);
        } catch (e) {
          console.error('Final buffer parse error:', e);
        }
      }
    } catch (err) {
      const timestamp = new Date().toLocaleTimeString();
      const errorMsg = err.message || '未知错误';
      setThinkingLogs(prev => [
        ...prev,
        { type: 'error', content: `[${timestamp}] ❌ 网络错误: ${errorMsg}`, timestamp },
      ]);
      setError(`分析出错: ${errorMsg}`);
      setCurrentStep(0);
    } finally {
      setIsLoading(false);
    }
  };

  // 文件类型映射
  const fileConfig = {
    gcode: { ext: '.nc', name: 'G代码', mime: 'text/plain' },
    schedule: { ext: '.pdf', name: '排产计划', mime: 'application/pdf' },
    quotation: { ext: '.pdf', name: '报价单', mime: 'application/pdf' },
    'process-card': { ext: '.pdf', name: '工艺卡', mime: 'application/pdf' },
  };

  // 预览文件
  const previewFile = async type => {
    if (!result?.id) return;

    try {
      const response = await axios.post(
        `${API_BASE}/export/${type}/${result.id}`,
        {},
        { responseType: 'blob' }
      );

      const config = fileConfig[type] || { ext: '.pdf', name: type, mime: 'application/pdf' };
      const blob = new Blob([response.data], { type: config.mime });
      const url = window.URL.createObjectURL(blob);

      setPreviewModal({
        open: true,
        type,
        url,
        title: config.name,
        filename: `${config.name}_${result.id}${config.ext}`,
      });
    } catch (err) {
      setError(`预览失败: ${err.message}`);
    }
  };

  // 下载文件（从预览或直接下载）
  const downloadFile = async (type, previewUrl = null) => {
    if (!result?.id) return;

    const config = fileConfig[type] || { ext: '.pdf', name: type };

    try {
      let url = previewUrl;

      if (!url) {
        const response = await axios.post(
          `${API_BASE}/export/${type}/${result.id}`,
          {},
          { responseType: 'blob' }
        );
        url = window.URL.createObjectURL(new Blob([response.data]));
      }

      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${config.name}_${result.id}${config.ext}`);
      document.body.appendChild(link);
      link.click();
      link.remove();

      if (!previewUrl) {
        window.URL.revokeObjectURL(url);
      }
    } catch (err) {
      setError(`下载失败: ${err.message}`);
    }
  };

  // 关闭预览
  const closePreview = () => {
    if (previewModal.url) {
      window.URL.revokeObjectURL(previewModal.url);
    }
    setPreviewModal({ open: false, type: '', url: '', title: '', filename: '' });
  };

  // 加载公司资源
  const loadResources = async () => {
    try {
      const response = await axios.get(`${API_BASE}/resources/`);
      setResources(response.data);
    } catch (err) {
      console.error('加载资源失败:', err);
    }
  };

  React.useEffect(() => {
    loadResources();
  }, []);

  // 处理流式事件
  const handleStreamEvent = data => {
    const timestamp = new Date().toLocaleTimeString();

    switch (data.type) {
      case 'start':
        setThinkingLogs(prev => [
          ...prev,
          {
            type: 'start',
            content: data.message,
            timestamp,
          },
        ]);
        break;

      case 'thinking':
        if (data.title) {
          setCurrentStep(data.step);
          setThinkingLogs(prev => [
            ...prev,
            {
              type: 'title',
              step: data.step,
              content: data.title,
              timestamp,
            },
          ]);
        }
        if (data.content) {
          setThinkingLogs(prev => [
            ...prev,
            {
              type: 'thinking',
              step: data.step,
              content: data.content,
              timestamp,
            },
          ]);
        }
        break;

      case 'step_complete':
        setThinkingLogs(prev => [
          ...prev,
          {
            type: 'step_complete',
            step: data.step,
            timestamp,
          },
        ]);
        break;

      case 'complete':
        setCurrentStep(6);
        setResult(data.result);
        setThinkingLogs(prev => [
          ...prev,
          {
            type: 'complete',
            content: data.message,
            timestamp,
          },
        ]);
        // 3秒后自动收起思考窗口
        setTimeout(() => {
          setThinkingLogs([]);
        }, 3000);
        break;

      case 'error':
        setError(data.message);
        setThinkingLogs(prev => [
          ...prev,
          {
            type: 'error',
            content: data.message,
            timestamp,
          },
        ]);
        break;
    }
  };

  // 分析步骤
  const steps = [
    { id: 1, name: '图纸分析', icon: FileText, description: '识别零件特征' },
    { id: 2, name: '工艺生成', icon: Settings, description: '制定加工方案' },
    { id: 3, name: 'G代码生成', icon: Code, description: '生成数控程序' },
    { id: 4, name: '排产计划', icon: Calendar, description: '安排生产任务' },
    { id: 5, name: '成本报价', icon: DollarSign, description: '计算加工费用' },
  ];

  return (
    <div className="min-h-screen bg-[#0f172a] text-gray-200 bg-grid">
      {/* 顶部导航 */}
      <header className="glass-panel sticky top-0 z-50 border-b border-gray-800">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="bg-blue-500/10 p-1.5 rounded-lg border border-blue-500/20 shadow-[0_0_15px_rgba(59,130,246,0.5)]">
                <svg className="h-6 w-6" viewBox="-15 -5 130 110" fill="none">
                  <rect
                    x="12"
                    y="28"
                    width="10"
                    height="40"
                    rx="5"
                    fill="#3b82f6"
                    transform="rotate(-22 17 48)"
                  />
                  <rect
                    x="35"
                    y="30"
                    width="10"
                    height="38"
                    rx="5"
                    fill="#3b82f6"
                    transform="rotate(-10 40 49)"
                  />
                  <rect
                    x="58"
                    y="28"
                    width="10"
                    height="40"
                    rx="5"
                    fill="#3b82f6"
                    transform="rotate(5 63 48)"
                  />
                  <rect
                    x="81"
                    y="32"
                    width="10"
                    height="38"
                    rx="5"
                    fill="#3b82f6"
                    transform="rotate(18 86 51)"
                  />
                </svg>
              </div>
              <div>
                <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-blue-400 tracking-tight">
                  慧银科技
                </h1>
                <p className="text-[10px] text-cyan-600/80 tracking-[0.2em] uppercase font-mono">
                  智能制造工艺分析系统
                </p>
              </div>
            </div>
            <nav className="flex space-x-1 bg-slate-900/80 p-1.5 rounded-lg border border-slate-700/50 backdrop-blur-md">
              <button
                onClick={() => setActiveTab('analysis')}
                className={`px-4 py-2 rounded-md font-medium text-sm transition-all duration-300 ${
                  activeTab === 'analysis'
                    ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 shadow-[0_0_10px_rgba(6,182,212,0.2)]'
                    : 'text-slate-400 hover:text-cyan-200 hover:bg-slate-800'
                }`}
              >
                工艺分析
              </button>
              <button
                onClick={() => setActiveTab('resources')}
                className={`px-4 py-2 rounded-md font-medium text-sm transition-all duration-300 ${
                  activeTab === 'resources'
                    ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 shadow-[0_0_10px_rgba(6,182,212,0.2)]'
                    : 'text-slate-400 hover:text-cyan-200 hover:bg-slate-800'
                }`}
              >
                资源配置
              </button>
              <button
                onClick={() => setActiveTab('knowledge')}
                className={`px-4 py-2 rounded-md font-medium text-sm transition-all duration-300 ${
                  activeTab === 'knowledge'
                    ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 shadow-[0_0_10px_rgba(6,182,212,0.2)]'
                    : 'text-slate-400 hover:text-cyan-200 hover:bg-slate-800'
                }`}
              >
                <span className="flex items-center">
                  <BookOpen className="h-4 w-4 mr-1.5" />
                  知识库
                </span>
              </button>
            </nav>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-8 relative z-10">
        {activeTab === 'analysis' ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* 左侧：输入区域 */}
            <div className="lg:col-span-1 space-y-6">
              {/* 文件上传 */}
              <div className="glass-card rounded-xl p-6 relative overflow-hidden group border-l-4 border-l-cyan-500/50">
                <div className="absolute top-0 right-0 w-32 h-32 bg-cyan-500/10 rounded-full blur-3xl -z-10 transition-all group-hover:bg-cyan-500/20"></div>
                <h2 className="text-sm font-bold mb-4 flex items-center text-cyan-300 uppercase tracking-wider">
                  <Upload className="h-4 w-4 mr-2" />
                  图纸输入
                </h2>
                <div
                  {...getRootProps()}
                  className={`border border-dashed rounded-lg p-8 text-center cursor-pointer transition-all duration-300 relative overflow-hidden ${
                    isDragActive
                      ? 'border-cyan-500 bg-cyan-500/10 shadow-[inset_0_0_20px_rgba(6,182,212,0.2)]'
                      : file
                      ? 'border-green-500/50 bg-green-500/5'
                      : 'border-slate-600 hover:border-cyan-500/50 hover:bg-slate-800/50'
                  }`}
                >
                  <input {...getInputProps()} />
                  {file ? (
                    <div className="text-green-400">
                      <div className="relative inline-block">
                        <CheckCircle className="h-10 w-10 mx-auto mb-3 drop-shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                        <div className="absolute inset-0 bg-green-500/20 blur-xl rounded-full"></div>
                      </div>
                      <p className="font-mono text-sm">{file.name}</p>
                      <p className="text-xs text-green-500/70 mt-1 uppercase tracking-wide">
                        准备就绪
                      </p>
                    </div>
                  ) : (
                    <div className="text-slate-400 group-hover:text-cyan-300 transition-colors">
                      <div className="relative inline-block mb-3">
                        <Upload className="h-10 w-10 mx-auto" />
                        <div className="absolute inset-0 bg-cyan-400/20 blur-lg rounded-full opacity-0 group-hover:opacity-100 transition-opacity"></div>
                      </div>
                      <p className="font-medium text-sm">拖放技术图纸</p>
                      <p className="text-xs mt-1 opacity-50 font-mono">DXF, DWG, PDF, JPG, PNG</p>
                    </div>
                  )}
                </div>
              </div>

              {/* 零件描述 */}
              <div className="glass-card rounded-xl p-6 border-l-4 border-l-blue-500/50">
                <h2 className="text-sm font-bold mb-4 flex items-center text-blue-300 uppercase tracking-wider">
                  <FileText className="h-4 w-4 mr-2" />
                  规格说明
                </h2>
                <textarea
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  placeholder="// 输入零件规格说明...
示例：
材料：45#钢
尺寸：直径50mm x 长度100mm
特征：M20螺纹（两端），键槽（中部）"
                  className="w-full h-32 px-4 py-3 bg-slate-900/80 border border-slate-700 rounded-lg text-slate-200 font-mono text-sm focus:ring-1 focus:ring-blue-500 focus:border-blue-500 transition-all resize-none placeholder-slate-600"
                />
              </div>

              {/* 生产参数 */}
              <div className="glass-card rounded-xl p-6 border-l-4 border-l-orange-500/50">
                <h2 className="text-sm font-bold mb-4 flex items-center text-orange-300 uppercase tracking-wider">
                  <Package className="h-4 w-4 mr-2" />
                  生产参数
                </h2>
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-slate-400 mb-1 uppercase tracking-wider">
                        数量
                      </label>
                      <input
                        type="number"
                        value={quantity}
                        onChange={e => setQuantity(parseInt(e.target.value) || 1)}
                        min="1"
                        className="input-tech w-full px-3 py-2 rounded border border-slate-700 bg-slate-900/80 text-orange-100 focus:border-orange-500 focus:ring-orange-500/20"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-400 mb-1 uppercase tracking-wider">
                        优先级
                      </label>
                      <select
                        value={priority}
                        onChange={e => setPriority(e.target.value)}
                        className="input-tech w-full px-3 py-2 rounded border border-slate-700 bg-slate-900/80 text-orange-100 focus:border-orange-500 focus:ring-orange-500/20"
                      >
                        <option value="low">标准</option>
                        <option value="normal">优先</option>
                        <option value="urgent">紧急</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-400 mb-1 uppercase tracking-wider">
                      交货日期
                    </label>
                    <input
                      type="date"
                      value={dueDate}
                      onChange={e => setDueDate(e.target.value)}
                      className="input-tech w-full px-3 py-2 rounded border border-slate-700 bg-slate-900/80 text-orange-100 focus:border-orange-500 focus:ring-orange-500/20"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-400 mb-1 uppercase tracking-wider">
                      客户编号
                    </label>
                    <input
                      type="text"
                      value={customer}
                      onChange={e => setCustomer(e.target.value)}
                      placeholder="例如: CLI-2024-001"
                      className="input-tech w-full px-3 py-2 rounded border border-slate-700 bg-slate-900/80 text-orange-100 focus:border-orange-500 focus:ring-orange-500/20"
                    />
                  </div>
                </div>
              </div>

              {/* 开始分析按钮 */}
              <button
                onClick={runFullAnalysis}
                disabled={isLoading || (!file && !description.trim())}
                className={`w-full py-4 rounded-lg font-bold text-lg flex items-center justify-center text-cyan-950 transition-all relative overflow-hidden group ${
                  isLoading || (!file && !description.trim())
                    ? 'bg-slate-800 text-slate-600 cursor-not-allowed border border-slate-700'
                    : 'bg-cyan-500 hover:bg-cyan-400 shadow-[0_0_20px_rgba(6,182,212,0.4)] border border-cyan-400'
                }`}
              >
                {/* Button Tech Overlay */}
                <div className="absolute top-0 left-0 w-2 h-2 border-t border-l border-white/50 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                <div className="absolute bottom-0 right-0 w-2 h-2 border-b border-r border-white/50 opacity-0 group-hover:opacity-100 transition-opacity"></div>

                {isLoading ? (
                  <>
                    <Loader2 className="h-5 w-5 mr-3 animate-spin" />
                    <span className="font-mono tracking-wider">处理中...</span>
                  </>
                ) : (
                  <>
                    <Play className="h-5 w-5 mr-3 fill-current" />
                    <span className="tracking-wider">开始分析</span>
                  </>
                )}
              </button>

              {/* 错误提示 */}
              {error && (
                <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-4 flex items-start animate-in fade-in slide-in-from-top-2">
                  <AlertCircle className="h-5 w-5 text-red-500 mr-2 flex-shrink-0 mt-0.5" />
                  <p className="text-red-400">{error}</p>
                </div>
              )}
            </div>

            {/* 右侧：结果展示 */}
            <div className="lg:col-span-2 space-y-6">
              {/* 分析进度 */}
              <div className="glass-card rounded-xl p-6 border-b-4 border-b-cyan-500/30">
                <h2 className="text-sm font-bold mb-6 text-slate-300 flex items-center uppercase tracking-wider">
                  <Activity className="h-4 w-4 mr-2 text-cyan-400" />
                  系统流程
                </h2>
                <div className="flex items-center justify-between relative z-0 px-4">
                  {/* 连接线背景 */}
                  <div className="absolute top-1/2 left-4 right-4 h-0.5 bg-slate-800 -z-10"></div>

                  {steps.map((step, index) => (
                    <React.Fragment key={step.id}>
                      <div className="flex flex-col items-center relative z-10 group">
                        <div
                          className={`w-10 h-10 rounded bg-slate-900 border flex items-center justify-center transition-all duration-300 ${
                            currentStep > step.id
                              ? 'border-green-500 text-green-500 shadow-[0_0_10px_rgba(16,185,129,0.3)]'
                              : currentStep === step.id
                              ? 'border-cyan-500 text-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.4)] scale-110'
                              : 'border-slate-700 text-slate-600'
                          }`}
                        >
                          {currentStep > step.id ? (
                            <CheckCircle className="h-5 w-5" />
                          ) : (
                            <step.icon
                              className={`h-5 w-5 ${
                                currentStep === step.id ? 'animate-pulse' : ''
                              }`}
                            />
                          )}
                        </div>
                        <p
                          className={`text-xs font-mono mt-3 transition-colors uppercase ${
                            currentStep >= step.id ? 'text-cyan-100' : 'text-slate-600'
                          }`}
                        >
                          {step.name}
                        </p>
                      </div>
                      {index < steps.length - 1 && (
                        <div
                          className={`flex-1 h-0.5 transition-all duration-1000 ${
                            currentStep > step.id
                              ? 'bg-gradient-to-r from-green-500 to-green-900'
                              : 'bg-transparent'
                          }`}
                        />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>

              {/* AI思考过程 */}
              {(isLoading || thinkingLogs.length > 0) && (
                <div className="ai-terminal rounded-lg overflow-hidden border border-slate-700 relative group shadow-2xl">
                  <div className="scanline"></div>
                  <div className="bg-slate-900 px-4 py-2 border-b border-slate-700 flex items-center justify-between">
                    <div className="flex items-center space-x-2">
                      <div className="flex space-x-1.5 opacity-50">
                        <div className="w-2 h-2 rounded-full bg-slate-500"></div>
                        <div className="w-2 h-2 rounded-full bg-slate-500"></div>
                        <div className="w-2 h-2 rounded-full bg-slate-500"></div>
                      </div>
                      <span className="text-xs text-cyan-500 font-mono ml-4 tracking-widest">
                        MISTRAL核心_V1.0 // 监控中
                      </span>
                    </div>
                    {isLoading && (
                      <div className="flex items-center text-cyan-400 text-xs font-mono">
                        <span className="animate-pulse mr-2">数据流处理中</span>
                        <Loader2 className="h-3 w-3 animate-spin" />
                      </div>
                    )}
                  </div>
                  <div
                    ref={thinkingRef}
                    className="p-6 h-[500px] overflow-y-auto font-mono text-xs leading-relaxed space-y-2 scroll-smooth bg-[#050a14]"
                  >
                    {thinkingLogs.map((log, index) => (
                      <ThinkingLogLine key={index} log={log} />
                    ))}
                    {isLoading && (
                      <div className="flex items-center text-green-500/70 mt-4">
                        <span className="mr-2 text-blue-500">➜</span>
                        <span className="ai-cursor"></span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* 分析结果 */}
              {result && (
                <>
                  {/* 审查结果(M6 质检关卡):编排的灵魂,交叉复核 + 不合格阻断导出 */}
                  {result.review && (
                    <ReviewCard review={result.review} exportable={result.exportable} />
                  )}

                  {/* 零件特征 */}
                  {result.part_analysis && <PartAnalysisCard data={result.part_analysis} />}

                  {/* 工艺方案 */}
                  {result.process_plan && <ProcessPlanCard data={result.process_plan} />}

                  {/* G代码预览 */}
                  {result.gcode_programs && result.gcode_programs.length > 0 && (
                    <GCodeCard programs={result.gcode_programs} />
                  )}

                  {/* 排产计划 */}
                  {result.production_schedule && <ScheduleCard data={result.production_schedule} />}

                  {/* 报价单 */}
                  {result.quotation && <QuotationCard data={result.quotation} />}

                  {/* 导出文档 */}
                  <div className="glass-card rounded-xl shadow-lg border-l-4 border-l-slate-500/50 p-6">
                    <h2 className="text-lg font-bold mb-4 flex items-center text-slate-300 uppercase tracking-wide">
                      <Download className="h-5 w-5 mr-2 text-slate-400" />
                      导出数据
                    </h2>
                    {result.exportable === false && (
                      <div className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                        ⛔ 审查未通过(blocked),已禁止导出。请按上方审查问题人工复核后再处理。
                      </div>
                    )}
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                      <ExportCard
                        label="G代码"
                        icon={Code}
                        description="数控程序 (.nc)"
                        disabled={result.exportable === false}
                        onPreview={() => previewFile('gcode')}
                        onDownload={() => downloadFile('gcode')}
                      />
                      <ExportCard
                        label="排产计划"
                        icon={FileSpreadsheet}
                        description="生产计划 (.pdf)"
                        disabled={result.exportable === false}
                        onPreview={() => previewFile('schedule')}
                        onDownload={() => downloadFile('schedule')}
                      />
                      <ExportCard
                        label="报价单"
                        icon={DollarSign}
                        description="成本估算 (.pdf)"
                        disabled={result.exportable === false}
                        onPreview={() => previewFile('quotation')}
                        onDownload={() => downloadFile('quotation')}
                      />
                      <ExportCard
                        label="工艺卡片"
                        icon={Printer}
                        description="工艺路线 (.pdf)"
                        disabled={result.exportable === false}
                        onPreview={() => previewFile('process-card')}
                        onDownload={() => downloadFile('process-card')}
                      />
                    </div>
                  </div>
                </>
              )}

              {/* 空状态 */}
              {!result && !isLoading && (
                <div className="glass-card rounded-xl shadow-inner p-12 text-center border border-slate-700/50 bg-slate-900/30">
                  <div className="bg-slate-800/50 p-6 rounded-full inline-block mb-6 border border-slate-700">
                    <Factory className="h-16 w-16 text-slate-500" />
                  </div>
                  <h3 className="text-xl font-bold text-gray-200 mb-2 uppercase tracking-wide">
                    准备就绪
                  </h3>
                  <p className="text-slate-400 max-w-md mx-auto font-mono text-sm">
                    上传技术图纸或输入规格说明，生成全面的制造分析报告。
                  </p>
                </div>
              )}
            </div>
          </div>
        ) : activeTab === 'resources' ? (
          // 资源配置页面
          <ResourcesPage resources={resources} onReload={loadResources} />
        ) : activeTab === 'knowledge' ? (
          // 知识库管理页面
          <KnowledgeManager />
        ) : null}
      </main>

      {/* 预览弹窗 */}
      {previewModal.open && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4 backdrop-blur-sm animate-in fade-in">
          <div className="glass-panel w-full max-w-6xl max-h-[90vh] flex flex-col rounded-xl border border-slate-600 shadow-2xl">
            {/* 弹窗头部 */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700 bg-slate-900/50">
              <h3 className="text-lg font-bold text-cyan-400 flex items-center uppercase tracking-widest">
                <Eye className="h-5 w-5 mr-3 text-cyan-500" />
                预览 - {previewModal.title}
              </h3>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => downloadFile(previewModal.type, previewModal.url)}
                  className="flex items-center px-4 py-2 bg-cyan-600/20 text-cyan-400 border border-cyan-500/50 rounded-lg hover:bg-cyan-600/30 transition-all font-mono text-xs font-bold"
                >
                  <Download className="h-4 w-4 mr-2" />
                  下载
                </button>
                <button
                  onClick={closePreview}
                  className="p-2 hover:bg-slate-700 rounded-lg transition-colors text-slate-400 hover:text-white"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>

            {/* 预览内容 */}
            <div className="flex-1 overflow-hidden p-1 bg-slate-950">
              {previewModal.type === 'gcode' ? (
                <iframe
                  src={previewModal.url}
                  className="w-full h-full bg-[#050a14] rounded-lg border border-slate-800"
                  title="G代码预览"
                />
              ) : (
                <iframe
                  src={previewModal.url}
                  className="w-full h-full rounded-lg bg-slate-100"
                  title={`${previewModal.title}预览`}
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// 零件特征分析卡片组件
function PartAnalysisCard({ data }) {
  const [expanded, setExpanded] = useState(true);

  const material = data.material || {};
  const dims = data.overall_dimensions || {};
  const features = data.features || [];

  // 复杂度颜色映射
  const complexityColor = {
    简单: 'bg-green-500/10 text-green-400 border border-green-500/30 shadow-[0_0_10px_rgba(34,197,94,0.1)]',
    中等: 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 shadow-[0_0_10px_rgba(234,179,8,0.1)]',
    复杂: 'bg-red-500/10 text-red-400 border border-red-500/30 shadow-[0_0_10px_rgba(239,68,68,0.1)]',
  };

  // 特征类型图标颜色
  const featureTypeColor = {
    孔: 'bg-blue-500/10 text-blue-300 border border-blue-500/20',
    轴: 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20',
    槽: 'bg-orange-500/10 text-orange-300 border border-orange-500/20',
    平面: 'bg-slate-500/10 text-slate-300 border border-slate-500/20',
    螺纹: 'bg-blue-500/10 text-blue-300 border border-blue-500/20',
    倒角: 'bg-teal-500/10 text-teal-300 border border-teal-500/20',
    圆角: 'bg-indigo-500/10 text-indigo-300 border border-indigo-500/20',
  };

  const getFeatureColor = type => {
    for (const [key, color] of Object.entries(featureTypeColor)) {
      if (type?.includes(key)) return color;
    }
    return 'bg-slate-500/10 text-slate-400';
  };

  return (
    <div className="glass-card rounded-xl overflow-hidden shadow-lg border-l-4 border-l-cyan-500/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/5 transition-colors group"
      >
        <div className="flex items-center">
          <div className="p-2 rounded-lg bg-cyan-500/10 mr-3 group-hover:bg-cyan-500/20 transition-colors">
            <Cpu className="h-5 w-5 text-cyan-400" />
          </div>
          <h2 className="text-lg font-bold text-gray-100 uppercase tracking-wide">零件分析</h2>
          <span className="ml-3 text-sm text-cyan-600/70 font-mono hidden sm:inline-block">
            // 检测特征
          </span>
          {data.part_name && (
            <span className="ml-3 px-3 py-1 bg-cyan-500/10 text-cyan-300 text-xs rounded-sm font-mono border border-cyan-500/20">
              {data.part_name}
            </span>
          )}
        </div>
        <ChevronRight
          className={`h-5 w-5 text-cyan-500/50 transition-transform duration-300 ${
            expanded ? 'rotate-90' : ''
          }`}
        />
      </button>

      {expanded && (
        <div className="px-6 pb-6 animate-in fade-in slide-in-from-top-4 duration-300">
          {/* 基本信息 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-16 h-16 bg-blue-500/5 rounded-full -mr-8 -mt-8"></div>
              <p className="text-[10px] text-blue-400 mb-1 font-mono uppercase tracking-wider">
                零件名称
              </p>
              <p className="font-bold text-gray-100 font-mono text-sm truncate">
                {data.part_name || 'UNKNOWN'}
              </p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-16 h-16 bg-blue-500/5 rounded-full -mr-8 -mt-8"></div>
              <p className="text-[10px] text-blue-400 mb-1 font-mono uppercase tracking-wider">
                零件编号
              </p>
              <p className="font-bold text-gray-100 font-mono text-sm">
                {data.part_number || 'N/A'}
              </p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-16 h-16 bg-green-500/5 rounded-full -mr-8 -mt-8"></div>
              <p className="text-[10px] text-green-400 mb-1 font-mono uppercase tracking-wider">
                材料
              </p>
              <p className="font-bold text-gray-100 font-mono text-sm truncate">
                {typeof material === 'object'
                  ? `${material.name || ''} ${material.grade || ''}`.trim() || 'UNSPECIFIED'
                  : material || 'UNSPECIFIED'}
              </p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50 relative overflow-hidden">
              <div className="absolute top-0 right-0 w-16 h-16 bg-orange-500/5 rounded-full -mr-8 -mt-8"></div>
              <p className="text-[10px] text-orange-400 mb-1 font-mono uppercase tracking-wider">
                硬度
              </p>
              <p className="font-bold text-gray-100 font-mono text-sm">
                {material.hardness || 'N/A'}
              </p>
            </div>
          </div>

          {/* 尺寸和属性 */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
            <div className="bg-slate-900/80 rounded border border-slate-700 p-2 text-center group hover:border-cyan-500/30 transition-colors">
              <p className="text-[10px] text-slate-500 uppercase">长度</p>
              <p className="font-mono text-cyan-100 font-bold">
                {dims.length || '-'}{' '}
                <span className="text-[10px] text-slate-600 font-normal">mm</span>
              </p>
            </div>
            <div className="bg-slate-900/80 rounded border border-slate-700 p-2 text-center group hover:border-cyan-500/30 transition-colors">
              <p className="text-[10px] text-slate-500 uppercase">宽度</p>
              <p className="font-mono text-cyan-100 font-bold">
                {dims.width || '-'}{' '}
                <span className="text-[10px] text-slate-600 font-normal">mm</span>
              </p>
            </div>
            <div className="bg-slate-900/80 rounded border border-slate-700 p-2 text-center group hover:border-cyan-500/30 transition-colors">
              <p className="text-[10px] text-slate-500 uppercase">高度</p>
              <p className="font-mono text-cyan-100 font-bold">
                {dims.height || '-'}{' '}
                <span className="text-[10px] text-slate-600 font-normal">mm</span>
              </p>
            </div>
            <div className="bg-slate-900/80 rounded border border-slate-700 p-2 text-center group hover:border-cyan-500/30 transition-colors">
              <p className="text-[10px] text-slate-500 uppercase">预估重量</p>
              <p className="font-mono text-cyan-100 font-bold">
                {data.estimated_weight || '-'}{' '}
                <span className="text-[10px] text-slate-600 font-normal">kg</span>
              </p>
            </div>
            <div className="bg-slate-900/80 rounded border border-slate-700 p-2 text-center group hover:border-cyan-500/30 transition-colors">
              <p className="text-[10px] text-slate-500 uppercase">复杂度</p>
              <span
                className={`inline-block px-1.5 py-0.5 rounded-[2px] text-[10px] font-bold uppercase tracking-wider mt-0.5 ${
                  complexityColor[data.complexity_level] || 'bg-slate-800 text-slate-500'
                }`}
              >
                {data.complexity_level || 'UNKNOWN'}
              </span>
            </div>
          </div>

          {/* 特征列表 */}
          {features.length > 0 && (
            <div className="border border-slate-700 rounded-lg overflow-hidden">
              <div className="bg-slate-900 px-4 py-2 border-b border-slate-700 flex justify-between items-center">
                <h3 className="text-xs font-bold text-cyan-500 uppercase tracking-widest flex items-center">
                  <span className="w-1.5 h-1.5 bg-cyan-500 rounded-full mr-2 animate-pulse"></span>
                  检测特征
                </h3>
                <span className="text-[10px] font-mono text-slate-500">
                  数量: {features.length}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm font-mono">
                  <thead>
                    <tr className="bg-slate-800/50 border-b border-slate-700">
                      <th className="px-4 py-2 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        特征
                      </th>
                      <th className="px-4 py-2 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        类型
                      </th>
                      <th className="px-4 py-2 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        尺寸
                      </th>
                      <th className="px-4 py-2 text-center text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        公差
                      </th>
                      <th className="px-4 py-2 text-center text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        粗糙度
                      </th>
                      <th className="px-4 py-2 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        备注
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800 bg-slate-900/30">
                    {features.map((feat, idx) => {
                      const dims = feat.dimensions || {};
                      const dimsStr =
                        Object.entries(dims)
                          .filter(([_, v]) => v !== null && v !== undefined)
                          .map(([k, v]) => {
                            const labels = {
                              diameter: '⌀',
                              depth: 'D',
                              length: 'L',
                              width: 'W',
                              height: 'H',
                              size: 'S',
                            };
                            return `${labels[k] || k.charAt(0).toUpperCase()}${v}`;
                          })
                          .join(' ') || '-';

                      return (
                        <tr key={idx} className="hover:bg-cyan-500/5 transition-colors">
                          <td className="px-4 py-2 font-medium text-slate-200">
                            {feat.name || '-'}
                          </td>
                          <td className="px-4 py-2">
                            <span
                              className={`inline-block px-1.5 py-0.5 rounded-[2px] text-[10px] font-bold uppercase ${getFeatureColor(
                                feat.type
                              )}`}
                            >
                              {feat.type || '-'}
                            </span>
                          </td>
                          <td className="px-4 py-2 text-cyan-100/80 text-xs">{dimsStr}</td>
                          <td className="px-4 py-2 text-center">
                            {feat.tolerance && feat.tolerance !== '-' ? (
                              <span className="text-[10px] text-yellow-500 font-bold">
                                {feat.tolerance}
                              </span>
                            ) : (
                              <span className="text-slate-700">-</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-center">
                            {feat.surface_finish && feat.surface_finish !== '-' ? (
                              <span className="text-[10px] text-green-500 font-bold">
                                {feat.surface_finish}
                              </span>
                            ) : (
                              <span className="text-slate-700">-</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-slate-500 text-[10px] truncate max-w-[150px]">
                            {feat.description || '-'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 备注 */}
          {data.notes && (
            <div className="mt-4 p-3 bg-orange-500/10 rounded border border-orange-500/20 flex items-start">
              <AlertCircle className="h-4 w-4 text-orange-400 mr-2 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-[10px] text-orange-400 font-bold uppercase tracking-wider mb-0.5">
                  Engineering Notes
                </p>
                <p className="text-sm text-orange-100/80 font-mono">{data.notes}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// 结果卡片组件(通用)
function ResultCard({ title, icon: Icon, data }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="glass-card rounded-xl overflow-hidden shadow-lg border border-slate-700/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/5 transition-colors group"
      >
        <div className="flex items-center">
          <Icon className="h-5 w-5 mr-3 text-cyan-400" />
          <h2 className="text-lg font-bold text-gray-200 uppercase tracking-wide">{title}</h2>
        </div>
        <ChevronRight
          className={`h-5 w-5 text-slate-500 transition-transform ${expanded ? 'rotate-90' : ''}`}
        />
      </button>
      {expanded && (
        <div className="px-6 pb-4">
          <pre className="bg-slate-900 rounded-lg p-4 overflow-auto text-xs font-mono text-green-400 border border-slate-800">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// 工艺方案卡片
function ProcessPlanCard({ data }) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="glass-card rounded-xl overflow-hidden shadow-lg border-l-4 border-l-blue-500/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/5 transition-colors group"
      >
        <div className="flex items-center">
          <div className="p-2 rounded-lg bg-blue-500/10 mr-3 group-hover:bg-blue-500/20 transition-colors">
            <Settings className="h-5 w-5 text-blue-400" />
          </div>
          <h2 className="text-lg font-bold text-gray-100 uppercase tracking-wide">工艺方案</h2>
          <span className="ml-3 px-3 py-1 bg-blue-500/10 text-blue-300 text-xs rounded-sm font-mono border border-blue-500/20">
            {data.total_steps || 0} 步骤
          </span>
        </div>
        <ChevronRight
          className={`h-5 w-5 text-blue-500/50 transition-transform duration-300 ${
            expanded ? 'rotate-90' : ''
          }`}
        />
      </button>

      {expanded && (
        <div className="px-6 pb-6">
          <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
            <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">原材料</p>
              <p className="font-medium text-slate-200 font-mono">
                {typeof data.material === 'object'
                  ? `${data.material?.name || ''} ${data.material?.grade || ''}`.trim()
                  : data.material}
              </p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">毛坯类型</p>
              <p className="font-medium text-slate-200 font-mono">{data.blank_type}</p>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">预计工时</p>
              <p className="font-medium text-slate-200 font-mono">{data.total_time_minutes} min</p>
            </div>
          </div>

          <div className="space-y-0 relative">
            <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-slate-800 z-0"></div>
            {(data.steps || []).map((step, index) => (
              <div key={index} className="relative z-10 mb-4 pl-4 last:mb-0">
                <div className="bg-slate-900/50 border border-slate-700/50 rounded-lg p-4 hover:border-blue-500/30 transition-all hover:bg-slate-800/50 group">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center">
                      <div className="absolute -left-[5px] w-3 h-3 bg-slate-900 border-2 border-blue-500 rounded-full"></div>
                      <span className="text-xs font-mono text-blue-400 font-bold mr-3">
                        OP-{String(step.step_number).padStart(2, '0')}
                      </span>
                      <span className="font-bold text-gray-200">{step.process_name}</span>
                      <span className="ml-3 px-2 py-0.5 bg-slate-800 text-slate-400 text-[10px] rounded uppercase border border-slate-700">
                        {step.equipment_type}
                      </span>
                    </div>
                    <span className="text-xs font-mono text-slate-500 flex items-center">
                      <Clock className="h-3 w-3 inline mr-1" />
                      {step.estimated_time_minutes}m
                    </span>
                  </div>
                  <p className="text-sm text-slate-400 pl-14 border-l border-slate-800 ml-1.5">
                    {step.description}
                  </p>

                  {step.tools_required &&
                    Array.isArray(step.tools_required) &&
                    step.tools_required.length > 0 && (
                      <div className="mt-3 ml-16 flex flex-wrap gap-2">
                        {step.tools_required.map((tool, i) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 bg-cyan-900/20 text-cyan-400 text-[10px] rounded border border-cyan-900/30 font-mono"
                          >
                            {tool}
                          </span>
                        ))}
                      </div>
                    )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// G代码卡片
function GCodeCard({ programs }) {
  const [expanded, setExpanded] = useState(false);
  const [activeProgram, setActiveProgram] = useState(0);

  return (
    <div className="glass-card rounded-xl overflow-hidden shadow-lg border-l-4 border-l-orange-500/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/5 transition-colors group"
      >
        <div className="flex items-center">
          <div className="p-2 rounded-lg bg-orange-500/10 mr-3 group-hover:bg-orange-500/20 transition-colors">
            <Code className="h-5 w-5 text-orange-400" />
          </div>
          <h2 className="text-lg font-bold text-gray-100 uppercase tracking-wide">数控程序</h2>
          <span className="ml-3 px-3 py-1 bg-orange-500/10 text-orange-300 text-xs rounded-sm font-mono border border-orange-500/20">
            {programs.length} 文件
          </span>
        </div>
        <ChevronRight
          className={`h-5 w-5 text-orange-500/50 transition-transform duration-300 ${
            expanded ? 'rotate-90' : ''
          }`}
        />
      </button>
      {expanded && (
        <div className="px-6 pb-6">
          <div className="flex space-x-2 mb-4 overflow-x-auto pb-2 scrollbar-hide">
            {programs.map((prog, index) => (
              <button
                key={index}
                onClick={() => setActiveProgram(index)}
                className={`px-4 py-2 rounded-sm whitespace-nowrap transition-all font-mono text-xs border ${
                  activeProgram === index
                    ? 'bg-orange-500/20 text-orange-300 border-orange-500/50'
                    : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:border-orange-500/30'
                }`}
              >
                {prog.program_number || `O${String(index + 1).padStart(4, '0')}`}
              </button>
            ))}
          </div>
          {programs[activeProgram] && (
            <div className="space-y-4">
              <div className="bg-slate-800/50 rounded border border-slate-700/50 p-3 text-xs grid grid-cols-2 gap-4">
                <div>
                  <span className="text-slate-500 uppercase tracking-wider block mb-1">
                    Machine
                  </span>
                  <span className="font-mono text-slate-200">
                    {programs[activeProgram].equipment}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 uppercase tracking-wider block mb-1">Setup</span>
                  <span className="font-mono text-slate-200">
                    {programs[activeProgram].setup_notes}
                  </span>
                </div>
              </div>
              <div className="relative group">
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(programs[activeProgram].code);
                    }}
                    className="px-2 py-1 bg-slate-700 text-xs text-white rounded hover:bg-slate-600"
                  >
                    COPY
                  </button>
                </div>
                <pre className="bg-[#050a14] text-green-400 rounded-lg p-4 overflow-auto text-xs font-mono border border-slate-700 shadow-inner max-h-96 custom-scrollbar">
                  <code>{programs[activeProgram].code}</code>
                </pre>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// 排产计划卡片
function ScheduleCard({ data }) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="glass-card rounded-xl overflow-hidden shadow-lg border-l-4 border-l-indigo-500/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/5 transition-colors group"
      >
        <div className="flex items-center">
          <div className="p-2 rounded-lg bg-indigo-500/10 mr-3 group-hover:bg-indigo-500/20 transition-colors">
            <Calendar className="h-5 w-5 text-indigo-400" />
          </div>
          <h2 className="text-lg font-bold text-gray-100 uppercase tracking-wide">生产排产</h2>
        </div>
        <ChevronRight
          className={`h-5 w-5 text-indigo-500/50 transition-transform duration-300 ${
            expanded ? 'rotate-90' : ''
          }`}
        />
      </button>
      {expanded && (
        <div className="px-6 pb-6">
          <div className="grid grid-cols-4 gap-4 mb-6">
            <div className="bg-slate-800/50 rounded border border-slate-700/50 p-3 text-center">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Quantity</p>
              <p className="font-mono font-bold text-slate-200">
                {data.quantity} <span className="text-[10px] font-normal text-slate-600">PCS</span>
              </p>
            </div>
            <div className="bg-slate-800/50 rounded border border-slate-700/50 p-3 text-center">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Start Date</p>
              <p className="font-mono font-bold text-slate-200 text-xs">{data.start_date}</p>
            </div>
            <div className="bg-slate-800/50 rounded border border-slate-700/50 p-3 text-center">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Due Date</p>
              <p className="font-mono font-bold text-slate-200 text-xs">{data.due_date}</p>
            </div>
            <div className="bg-slate-800/50 rounded border border-slate-700/50 p-3 text-center">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">
                Utilization
              </p>
              <p className="font-mono font-bold text-indigo-400">
                {((data.utilization_rate || 0) * 100).toFixed(1)}%
              </p>
            </div>
          </div>

          <div className="rounded-lg border border-slate-700 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead className="bg-slate-900 border-b border-slate-700">
                  <tr>
                    <th className="px-4 py-3 text-left text-slate-400 font-bold uppercase tracking-wider">
                      Operation
                    </th>
                    <th className="px-4 py-3 text-left text-slate-400 font-bold uppercase tracking-wider">
                      Machine
                    </th>
                    <th className="px-4 py-3 text-left text-slate-400 font-bold uppercase tracking-wider">
                      Operator
                    </th>
                    <th className="px-4 py-3 text-left text-slate-400 font-bold uppercase tracking-wider">
                      Start
                    </th>
                    <th className="px-4 py-3 text-left text-slate-400 font-bold uppercase tracking-wider">
                      End
                    </th>
                    <th className="px-4 py-3 text-left text-slate-400 font-bold uppercase tracking-wider">
                      Duration
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800 bg-slate-900/40">
                  {(data.tasks || []).map((task, index) => (
                    <tr key={index} className="hover:bg-white/5 transition-colors">
                      <td className="px-4 py-3 font-bold text-slate-200 border-l-2 border-transparent hover:border-indigo-500 transition-all">
                        {task.process_name}
                      </td>
                      <td className="px-4 py-3 text-slate-300">{task.equipment_name}</td>
                      <td className="px-4 py-3 text-slate-400">{task.operator_name}</td>
                      <td className="px-4 py-3 text-slate-400">{task.start_time}</td>
                      <td className="px-4 py-3 text-slate-400">{task.end_time}</td>
                      <td className="px-4 py-3 text-indigo-300">{task.duration_minutes}m</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// 报价单卡片
function QuotationCard({ data }) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="glass-card rounded-xl overflow-hidden shadow-lg border-l-4 border-l-emerald-500/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/5 transition-colors group"
      >
        <div className="flex items-center">
          <div className="p-2 rounded-lg bg-emerald-500/10 mr-3 group-hover:bg-emerald-500/20 transition-colors">
            <DollarSign className="h-5 w-5 text-emerald-400" />
          </div>
          <h2 className="text-lg font-bold text-gray-100 uppercase tracking-wide">报价单</h2>
          <span className="ml-3 text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-emerald-400 to-teal-400 font-mono">
            ¥ {(data.total || 0).toFixed(2)}
          </span>
        </div>
        <ChevronRight
          className={`h-5 w-5 text-emerald-500/50 transition-transform duration-300 ${
            expanded ? 'rotate-90' : ''
          }`}
        />
      </button>
      {expanded && (
        <div className="px-6 pb-6">
          <div className="flex justify-between items-center mb-6 text-xs text-slate-500 border-b border-slate-700/50 pb-2">
            <span className="font-mono">
              编号: {data.quotation_number || `QT-${Date.now().toString().slice(-6)}`}
            </span>
            <span className="font-mono">有效期: {data.valid_until || '30天'}</span>
          </div>

          <div className="rounded-lg border border-slate-700 overflow-hidden mb-6">
            <table className="w-full text-xs font-mono">
              <thead className="bg-slate-900 border-b border-slate-700">
                <tr>
                  <th className="px-4 py-3 text-left text-slate-400 uppercase tracking-wider">
                    项目
                  </th>
                  <th className="px-4 py-3 text-left text-slate-400 uppercase tracking-wider">
                    描述
                  </th>
                  <th className="px-4 py-3 text-right text-slate-400 uppercase tracking-wider">
                    数量
                  </th>
                  <th className="px-4 py-3 text-center text-slate-400 uppercase tracking-wider">
                    单位
                  </th>
                  <th className="px-4 py-3 text-right text-slate-400 uppercase tracking-wider">
                    单价
                  </th>
                  <th className="px-4 py-3 text-right text-slate-400 uppercase tracking-wider">
                    金额
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-900/40">
                {(data.items || []).map((item, index) => (
                  <tr key={index}>
                    <td className="px-4 py-3 text-slate-300">{index + 1}</td>
                    <td className="px-4 py-3 text-slate-200 font-medium">
                      {item.description || item.item}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-400">{item.quantity}</td>
                    <td className="px-4 py-3 text-center text-slate-500">{item.unit}</td>
                    <td className="px-4 py-3 text-right text-slate-300">
                      ¥{(item.unit_price || 0).toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-right text-emerald-300">
                      ¥{(item.total_price || 0).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="space-y-2 pt-2">
              <div className="p-3 bg-slate-800/50 rounded border border-slate-700/50">
                <p className="text-[10px] text-slate-500 uppercase mb-1">成本分析</p>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden flex">
                  <div style={{ width: '40%' }} className="bg-blue-500 h-full"></div>
                  <div style={{ width: '30%' }} className="bg-cyan-500 h-full"></div>
                  <div style={{ width: '20%' }} className="bg-orange-500 h-full"></div>
                  <div style={{ width: '10%' }} className="bg-green-500 h-full"></div>
                </div>
                <div className="flex justify-between mt-2 text-[10px] text-slate-400">
                  <span className="flex items-center">
                    <div className="w-2 h-2 bg-blue-500 rounded-full mr-1"></div>材料
                  </span>
                  <span className="flex items-center">
                    <div className="w-2 h-2 bg-cyan-500 rounded-full mr-1"></div>人工
                  </span>
                  <span className="flex items-center">
                    <div className="w-2 h-2 bg-orange-500 rounded-full mr-1"></div>机时
                  </span>
                  <span className="flex items-center">
                    <div className="w-2 h-2 bg-green-500 rounded-full mr-1"></div>管理
                  </span>
                </div>
              </div>
            </div>

            <div className="space-y-2 text-sm font-mono">
              <div className="flex justify-between text-slate-400">
                <span>小计</span>
                <span>¥ {(data.subtotal || 0).toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>管理费 ({((data.overhead_rate || 0.15) * 100).toFixed(0)}%)</span>
                <span>¥ {(data.overhead || 0).toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-slate-400 border-b border-slate-700 pb-2">
                <span>利润 ({((data.profit_rate || 0.2) * 100).toFixed(0)}%)</span>
                <span>¥ {(data.profit || 0).toFixed(2)}</span>
              </div>
              <div className="flex justify-between font-bold text-xl pt-2 text-emerald-400">
                <span>总计</span>
                <span>¥ {(data.total || 0).toFixed(2)}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// 下载按钮组件
function DownloadButton({ label, icon: Icon, onClick }) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center justify-center p-4 border border-slate-700 rounded-lg hover:border-cyan-500 hover:bg-cyan-500/10 transition-all group bg-slate-800/50"
    >
      <Icon className="h-8 w-8 text-slate-500 group-hover:text-cyan-400 mb-2 transition-colors" />
      <span className="text-xs font-bold text-slate-400 group-hover:text-cyan-300 font-mono uppercase tracking-wide transition-colors">
        {label}
      </span>
    </button>
  );
}

// 导出卡片组件（带预览和下载）
function ExportCard({ label, icon: Icon, description, onPreview, onDownload, disabled = false }) {
  return (
    <div className={`glass-card p-4 rounded-lg flex flex-col items-center justify-between border border-slate-700 transition-all group ${disabled ? 'opacity-40 grayscale' : 'hover:border-cyan-500/50 hover:bg-slate-800/50'}`}>
      <div className="flex flex-col items-center text-center w-full mb-4">
        <div className="w-10 h-10 bg-slate-800 rounded-lg flex items-center justify-center mb-3 group-hover:bg-cyan-500/10 transition-colors border border-slate-700 group-hover:border-cyan-500/30">
          <Icon className="h-5 w-5 text-slate-400 group-hover:text-cyan-400 transition-colors" />
        </div>
        <h4 className="font-bold text-slate-200 text-sm uppercase tracking-wide">{label}</h4>
        <p className="text-[10px] text-slate-500 mt-1 font-mono">{description}</p>
      </div>

      <div className="flex items-center gap-2 w-full">
        <button
          onClick={onPreview}
          disabled={disabled}
          className="flex-1 flex items-center justify-center px-2 py-1.5 text-xs font-mono text-cyan-300 border border-cyan-500/20 bg-cyan-500/5 rounded hover:bg-cyan-500/10 transition-colors disabled:cursor-not-allowed disabled:hover:bg-cyan-500/5"
          title={disabled ? '审查未通过,已禁止导出' : '预览'}
        >
          <Eye className="h-3 w-3 mr-1" />
          查看
        </button>
        <button
          onClick={onDownload}
          disabled={disabled}
          className="flex-1 flex items-center justify-center px-2 py-1.5 text-xs font-mono text-slate-900 bg-cyan-500 hover:bg-cyan-400 rounded transition-colors font-bold disabled:cursor-not-allowed disabled:hover:bg-cyan-500"
          title={disabled ? '审查未通过,已禁止导出' : '下载'}
        >
          <Download className="h-3 w-3 mr-1" />
          保存
        </button>
      </div>
    </div>
  );
}

// 审查结果卡片(M6 质检关卡):展示交叉复核问题,分级着色;blocked 时配合禁用导出
function ReviewCard({ review, exportable }) {
  const status = review.status || 'approved';
  const issues = review.issues || [];
  const theme = {
    approved: { border: 'border-l-green-500', text: 'text-green-300', label: '✅ 审查通过' },
    requires_review: { border: 'border-l-amber-500', text: 'text-amber-300', label: '⚠️ 需人工复核' },
    blocked: { border: 'border-l-red-500', text: 'text-red-300', label: '⛔ 审查阻断(禁止导出)' },
  }[status] || { border: 'border-l-slate-500', text: 'text-slate-300', label: status };

  const sevStyle = {
    critical: 'bg-red-500/15 text-red-300 border-red-500/30',
    major: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    minor: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  };

  return (
    <div className={`glass-card rounded-xl shadow-lg border-l-4 ${theme.border} p-6`}>
      <h2 className={`text-lg font-bold mb-1 flex items-center uppercase tracking-wide ${theme.text}`}>
        <ShieldCheck className="h-5 w-5 mr-2" />
        工艺审查 (M6 交叉复核)
      </h2>
      <p className={`text-sm mb-4 ${theme.text}`}>
        {theme.label} · {review.summary || `共 ${issues.length} 条问题`}
      </p>
      {issues.length === 0 ? (
        <p className="text-sm text-slate-400">未发现问题,方案可放行。</p>
      ) : (
        <ul className="space-y-2">
          {issues.map((it, i) => (
            <li
              key={i}
              className={`text-xs font-mono px-3 py-2 rounded border ${sevStyle[it.severity] || sevStyle.minor}`}
            >
              <span className="font-bold uppercase mr-2">[{it.severity || 'minor'}]</span>
              <span className="opacity-70 mr-2">{it.rule}</span>
              {it.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// 资源配置页面（可手动编辑）
function ResourcesPage({ resources, onReload }) {
  const [showEquipmentModal, setShowEquipmentModal] = useState(false);
  const [showPersonnelModal, setShowPersonnelModal] = useState(false);
  const [showMaterialModal, setShowMaterialModal] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [notification, setNotification] = useState(null);
  const [activeConfig, setActiveConfig] = useState('equipment');

  // 设备表单
  const [equipmentForm, setEquipmentForm] = useState({
    id: '',
    name: '',
    type: 'CNC_LATHE',
    brand: '',
    model: '',
    capabilities: '',
    hourly_rate: 80,
    status: 'available',
  });

  // 人员表单
  const [personnelForm, setPersonnelForm] = useState({
    id: '',
    name: '',
    skills: '',
    level: 'intermediate',
    shift: 'day',
    hourly_rate: 50,
  });

  // 材料表单
  const [materialForm, setMaterialForm] = useState({ name: '', price: 10 });

  const showNotice = (msg, type = 'success') => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 2000);
  };

  // 添加设备
  const handleAddEquipment = async () => {
    const data = {
      ...equipmentForm,
      id: equipmentForm.id || `eq_${Date.now()}`,
      capabilities: equipmentForm.capabilities
        .split(',')
        .map(s => s.trim())
        .filter(Boolean),
    };
    try {
      await axios.post(`${API_BASE}/resources/equipment`, data);
      showNotice('设备已添加');
      setShowEquipmentModal(false);
      setEquipmentForm({
        id: '',
        name: '',
        type: 'CNC_LATHE',
        brand: '',
        model: '',
        capabilities: '',
        hourly_rate: 80,
        status: 'available',
      });
      onReload();
    } catch (e) {
      showNotice('添加失败', 'error');
    }
  };

  // 删除设备
  const handleDeleteEquipment = async id => {
    if (!confirm('确定删除此设备？')) return;
    try {
      await axios.delete(`${API_BASE}/resources/equipment/${id}`);
      showNotice('设备已删除');
      onReload();
    } catch (e) {
      showNotice('删除失败', 'error');
    }
  };

  // 添加人员
  const handleAddPersonnel = async () => {
    const data = {
      ...personnelForm,
      id: personnelForm.id || `p_${Date.now()}`,
      skills: personnelForm.skills
        .split(',')
        .map(s => s.trim())
        .filter(Boolean),
    };
    try {
      await axios.post(`${API_BASE}/resources/personnel`, data);
      showNotice('人员已添加');
      setShowPersonnelModal(false);
      setPersonnelForm({
        id: '',
        name: '',
        skills: '',
        level: 'intermediate',
        shift: 'day',
        hourly_rate: 50,
      });
      onReload();
    } catch (e) {
      showNotice('添加失败', 'error');
    }
  };

  // 删除人员
  const handleDeletePersonnel = async id => {
    if (!confirm('确定删除此人员？')) return;
    try {
      await axios.delete(`${API_BASE}/resources/personnel/${id}`);
      showNotice('人员已删除');
      onReload();
    } catch (e) {
      showNotice('删除失败', 'error');
    }
  };

  // 添加材料
  const handleAddMaterial = async () => {
    const newCosts = {
      ...(resources.material_costs || {}),
      [materialForm.name]: materialForm.price,
    };
    try {
      await axios.put(`${API_BASE}/resources/`, { ...resources, material_costs: newCosts });
      showNotice('材料已添加');
      setShowMaterialModal(false);
      setMaterialForm({ name: '', price: 10 });
      onReload();
    } catch (e) {
      showNotice('添加失败', 'error');
    }
  };

  // 删除材料
  const handleDeleteMaterial = async name => {
    if (!confirm(`确定删除材料 ${name}？`)) return;
    const newCosts = { ...(resources.material_costs || {}) };
    delete newCosts[name];
    try {
      await axios.put(`${API_BASE}/resources/`, { ...resources, material_costs: newCosts });
      showNotice('材料已删除');
      onReload();
    } catch (e) {
      showNotice('删除失败', 'error');
    }
  };

  if (!resources) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-cyan-400">
        <Loader2 className="h-8 w-8 animate-spin mb-4" />
        <p className="font-mono text-sm tracking-wider">连接资源数据库...</p>
      </div>
    );
  }

  const renderContent = () => {
    switch (activeConfig) {
      case 'equipment':
        return (
          <div className="space-y-4">
            {(resources.equipment || []).map((eq, idx) => (
              <div
                key={idx}
                className="glass-card p-4 rounded-lg flex justify-between items-center group hover:bg-slate-800/50 border border-slate-700/50 hover:border-cyan-500/30 transition-all"
              >
                <div className="flex items-center">
                  <div className="p-3 bg-cyan-900/20 rounded-lg mr-4 group-hover:bg-cyan-900/40 transition-colors border border-cyan-500/20">
                    <Settings className="h-5 w-5 text-cyan-400" />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-200 font-mono tracking-wide">{eq.name}</h3>
                    <p className="text-xs text-slate-500 font-mono">ID: {eq.id}</p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className="text-cyan-400 font-mono text-lg font-bold">
                      ¥{eq.hourly_rate}/h
                    </div>
                    <div className="text-[10px] text-slate-600 uppercase tracking-wider">
                      机时费率
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        setEditingItem(eq);
                        setEquipmentForm({
                          id: eq.id,
                          name: eq.name,
                          type: eq.type,
                          brand: eq.brand || '',
                          model: eq.model || '',
                          capabilities: Array.isArray(eq.capabilities)
                            ? eq.capabilities.join(', ')
                            : '',
                          hourly_rate: eq.hourly_rate,
                          status: eq.status || 'available',
                        });
                        setShowEquipmentModal(true);
                      }}
                      className="p-2 hover:bg-cyan-500/10 rounded transition-colors text-cyan-400 hover:text-cyan-300"
                      title="编辑"
                    >
                      <Settings className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => handleDeleteEquipment(eq.id)}
                      className="p-2 hover:bg-red-500/10 rounded transition-colors text-slate-500 hover:text-red-400"
                      title="删除"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        );
      case 'personnel':
        return (
          <div className="space-y-4">
            {resources.personnel.map((p, idx) => (
              <div
                key={idx}
                className="glass-card p-4 rounded-lg flex justify-between items-center group hover:bg-slate-800/50 border border-slate-700/50 hover:border-blue-500/30 transition-all"
              >
                <div className="flex items-center">
                  <div className="p-3 bg-blue-900/20 rounded-lg mr-4 group-hover:bg-blue-900/40 transition-colors border border-blue-500/20">
                    <Users className="h-5 w-5 text-blue-400" />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-200 font-mono tracking-wide">{p.role}</h3>
                    <div className="flex gap-2 mt-1">
                      {p.skills.map((skill, i) => (
                        <span
                          key={i}
                          className="text-[10px] bg-blue-500/10 text-blue-300 px-1.5 py-0.5 rounded border border-blue-500/20 font-mono"
                        >
                          {skill}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <div className="text-blue-400 font-mono text-lg font-bold">
                      ¥{p.hourly_rate}/h
                    </div>
                    <div className="text-[10px] text-slate-600 uppercase tracking-wider">时薪</div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        setEditingItem(p);
                        setPersonnelForm({
                          id: p.id,
                          name: p.name || p.role,
                          skills: Array.isArray(p.skills) ? p.skills.join(', ') : '',
                          level: p.level || 'intermediate',
                          shift: p.shift || 'day',
                          hourly_rate: p.hourly_rate,
                        });
                        setShowPersonnelModal(true);
                      }}
                      className="p-2 hover:bg-blue-500/10 rounded transition-colors text-blue-400 hover:text-blue-300"
                      title="编辑"
                    >
                      <Settings className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => handleDeletePersonnel(p.id)}
                      className="p-2 hover:bg-red-500/10 rounded transition-colors text-slate-500 hover:text-red-400"
                      title="删除"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        );
      case 'materials':
        return (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Object.entries(resources.material_costs).map(([material, cost], idx) => (
              <div
                key={idx}
                className="glass-card p-4 rounded-lg flex justify-between items-center border border-slate-700/50 hover:border-green-500/30 transition-all hover:bg-slate-800/50"
              >
                <div className="flex items-center">
                  <div className="w-2 h-2 rounded-sm bg-green-500 mr-3 shadow-[0_0_8px_rgba(34,197,94,0.5)] rotate-45"></div>
                  <span className="text-slate-300 font-medium font-mono">{material}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-green-400 font-mono font-bold">
                    ¥{cost}
                    <span className="text-xs text-slate-600 font-normal ml-1">/KG</span>
                  </span>
                  <button
                    onClick={() => handleDeleteMaterial(material)}
                    className="p-1.5 hover:bg-red-500/10 rounded transition-colors text-slate-500 hover:text-red-400"
                    title="删除"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <>
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        {/* 侧边栏 */}
        <div className="lg:col-span-1">
          <div className="glass-card rounded-xl p-4 sticky top-24 border border-slate-700">
            <h2 className="text-sm font-bold text-cyan-400 mb-6 px-2 flex items-center uppercase tracking-widest border-b border-slate-800 pb-4">
              <Factory className="h-4 w-4 mr-2" />
              Resource Mgmt
            </h2>
            <nav className="space-y-2">
              {[
                {
                  id: 'equipment',
                  name: 'Equipment',
                  icon: Wrench,
                  color: 'text-cyan-400',
                  active: 'bg-cyan-500/10 border-cyan-500/50 text-cyan-300',
                },
                {
                  id: 'personnel',
                  name: 'Personnel',
                  icon: Users,
                  color: 'text-blue-400',
                  active: 'bg-blue-500/10 border-blue-500/50 text-blue-300',
                },
                {
                  id: 'materials',
                  name: 'Materials',
                  icon: Package,
                  color: 'text-green-400',
                  active: 'bg-green-500/10 border-green-500/50 text-green-300',
                },
              ].map(item => (
                <button
                  key={item.id}
                  onClick={() => setActiveConfig(item.id)}
                  className={`w-full flex items-center px-4 py-3 rounded-lg transition-all duration-300 border font-mono text-sm ${
                    activeConfig === item.id
                      ? `${item.active} shadow-[0_0_15px_rgba(0,0,0,0.3)]`
                      : 'border-transparent text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                  }`}
                >
                  <item.icon
                    className={`h-4 w-4 mr-3 ${
                      activeConfig === item.id ? 'opacity-100' : 'opacity-50'
                    }`}
                  />
                  {item.name}
                </button>
              ))}
            </nav>

            <div className="mt-8 pt-6 border-t border-slate-800 px-2">
              <div className="flex items-center justify-between mb-4">
                <span className="text-[10px] text-slate-500 uppercase tracking-wider">
                  系统参数
                </span>
                <Settings className="h-3 w-3 text-slate-600" />
              </div>
              <div className="space-y-4">
                <div>
                  <div className="flex justify-between items-center text-[10px] font-mono mb-1">
                    <span className="text-slate-400">管理费率</span>
                    <div className="flex items-center">
                      <input
                        type="number"
                        value={(resources.overhead_rate * 100).toFixed(0)}
                        onChange={async e => {
                          const newRate = parseFloat(e.target.value) / 100;
                          if (newRate >= 0 && newRate <= 1) {
                            try {
                              await axios.put(`${API_BASE}/resources/`, {
                                ...resources,
                                overhead_rate: newRate,
                              });
                              onReload();
                              showNotice('管理费率已更新');
                            } catch (err) {
                              showNotice('更新失败', 'error');
                            }
                          }
                        }}
                        className="w-12 px-1 py-0.5 bg-slate-900 border border-slate-700 rounded text-cyan-400 text-right font-mono text-[10px] focus:border-cyan-500 focus:outline-none"
                        min="0"
                        max="100"
                      />
                      <span className="text-cyan-400 ml-1">%</span>
                    </div>
                  </div>
                  <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-cyan-600 relative"
                      style={{ width: `${resources.overhead_rate * 100}%` }}
                    >
                      <div className="absolute right-0 top-0 bottom-0 w-1 bg-cyan-400 shadow-[0_0_5px_rgba(6,182,212,0.8)]"></div>
                    </div>
                  </div>
                </div>
                <div>
                  <div className="flex justify-between items-center text-[10px] font-mono mb-1">
                    <span className="text-slate-400">利润率</span>
                    <div className="flex items-center">
                      <input
                        type="number"
                        value={(resources.profit_rate * 100).toFixed(0)}
                        onChange={async e => {
                          const newRate = parseFloat(e.target.value) / 100;
                          if (newRate >= 0 && newRate <= 1) {
                            try {
                              await axios.put(`${API_BASE}/resources/`, {
                                ...resources,
                                profit_rate: newRate,
                              });
                              onReload();
                              showNotice('利润率已更新');
                            } catch (err) {
                              showNotice('更新失败', 'error');
                            }
                          }
                        }}
                        className="w-12 px-1 py-0.5 bg-slate-900 border border-slate-700 rounded text-green-400 text-right font-mono text-[10px] focus:border-green-500 focus:outline-none"
                        min="0"
                        max="100"
                      />
                      <span className="text-green-400 ml-1">%</span>
                    </div>
                  </div>
                  <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-600 relative"
                      style={{ width: `${resources.profit_rate * 100}%` }}
                    >
                      <div className="absolute right-0 top-0 bottom-0 w-1 bg-green-400 shadow-[0_0_5px_rgba(34,197,94,0.8)]"></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 主内容 */}
        <div className="lg:col-span-3">
          <div className="glass-card rounded-xl p-6 h-[600px] border border-slate-700/50 bg-[#0b1121]/80 flex flex-col">
            <div className="flex justify-between items-center mb-6 border-b border-slate-800 pb-4">
              <h2 className="text-lg font-bold text-gray-100 flex items-center uppercase tracking-wider">
                {activeConfig === 'equipment' && <Wrench className="mr-3 text-cyan-400 h-5 w-5" />}
                {activeConfig === 'personnel' && <Users className="mr-3 text-blue-400 h-5 w-5" />}
                {activeConfig === 'materials' && (
                  <Package className="mr-3 text-green-400 h-5 w-5" />
                )}
                {activeConfig === 'equipment'
                  ? '设备清单'
                  : activeConfig === 'personnel'
                  ? '人员配置'
                  : '材料成本库'}
              </h2>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => {
                    if (activeConfig === 'equipment') setShowEquipmentModal(true);
                    else if (activeConfig === 'personnel') setShowPersonnelModal(true);
                    else if (activeConfig === 'materials') setShowMaterialModal(true);
                    setEditingItem(null);
                  }}
                  className="px-4 py-2 bg-cyan-600/20 text-cyan-400 border border-cyan-500/50 rounded-lg hover:bg-cyan-600/30 transition-all flex items-center space-x-2 font-mono text-sm"
                >
                  <Plus className="h-4 w-4" />
                  <span>新增</span>
                </button>
                <button
                  onClick={onReload}
                  className="p-2 hover:bg-white/5 rounded-lg transition-colors text-slate-500 hover:text-cyan-400 group"
                  title="刷新数据"
                >
                  <Activity className="h-5 w-5 group-hover:animate-pulse" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">{renderContent()}</div>
          </div>
        </div>
      </div>

      {/* 通知提示 */}
      {notification && (
        <div
          className={`fixed top-4 right-4 px-6 py-3 rounded-lg shadow-lg z-50 animate-in slide-in-from-top ${
            notification.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
          }`}
        >
          {notification.msg}
        </div>
      )}

      {/* 设备模态框 */}
      {showEquipmentModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="glass-panel w-full max-w-2xl rounded-xl border border-slate-600 shadow-2xl">
            <div className="p-6 border-b border-slate-700 flex items-center justify-between bg-slate-900/50">
              <h3 className="text-lg font-bold text-cyan-400 uppercase tracking-widest flex items-center">
                <Wrench className="h-5 w-5 mr-2" />
                {editingItem ? '编辑设备' : '新增设备'}
              </h3>
              <button
                onClick={() => {
                  setShowEquipmentModal(false);
                  setEditingItem(null);
                }}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
            <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    设备ID
                  </label>
                  <input
                    type="text"
                    value={equipmentForm.id}
                    onChange={e => setEquipmentForm({ ...equipmentForm, id: e.target.value })}
                    placeholder="例如: CNC-001"
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    设备名称
                  </label>
                  <input
                    type="text"
                    value={equipmentForm.name}
                    onChange={e => setEquipmentForm({ ...equipmentForm, name: e.target.value })}
                    placeholder="例如: 数控车床-1号"
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    设备类型
                  </label>
                  <select
                    value={equipmentForm.type}
                    onChange={e => setEquipmentForm({ ...equipmentForm, type: e.target.value })}
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                  >
                    <option value="CNC_LATHE">数控车床</option>
                    <option value="CNC_MILL">数控铣床</option>
                    <option value="GRINDER">磨床</option>
                    <option value="DRILL">钻床</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    状态
                  </label>
                  <select
                    value={equipmentForm.status}
                    onChange={e => setEquipmentForm({ ...equipmentForm, status: e.target.value })}
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                  >
                    <option value="available">可用</option>
                    <option value="busy">使用中</option>
                    <option value="maintenance">维护中</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    品牌
                  </label>
                  <input
                    type="text"
                    value={equipmentForm.brand}
                    onChange={e => setEquipmentForm({ ...equipmentForm, brand: e.target.value })}
                    placeholder="例如: 沈阳机床"
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    型号
                  </label>
                  <input
                    type="text"
                    value={equipmentForm.model}
                    onChange={e => setEquipmentForm({ ...equipmentForm, model: e.target.value })}
                    placeholder="例如: CAK6150"
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  加工能力（逗号分隔）
                </label>
                <input
                  type="text"
                  value={equipmentForm.capabilities}
                  onChange={e =>
                    setEquipmentForm({ ...equipmentForm, capabilities: e.target.value })
                  }
                  placeholder="例如: 车削, 螺纹加工, 端面加工"
                  className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  机时费率 (¥/小时)
                </label>
                <input
                  type="number"
                  value={equipmentForm.hourly_rate}
                  onChange={e =>
                    setEquipmentForm({
                      ...equipmentForm,
                      hourly_rate: parseFloat(e.target.value) || 0,
                    })
                  }
                  className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                />
              </div>
            </div>
            <div className="p-6 border-t border-slate-700 bg-slate-900/50 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setShowEquipmentModal(false);
                  setEditingItem(null);
                }}
                className="px-6 py-2 border border-slate-600 text-slate-300 rounded-lg hover:bg-slate-800 transition-colors font-mono text-sm"
              >
                取消
              </button>
              <button
                onClick={handleAddEquipment}
                className="px-6 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-500 transition-colors font-mono text-sm font-bold tracking-wide shadow-[0_0_15px_rgba(6,182,212,0.3)]"
              >
                {editingItem ? '保存' : '添加'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 人员模态框 */}
      {showPersonnelModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="glass-panel w-full max-w-2xl rounded-xl border border-slate-600 shadow-2xl">
            <div className="p-6 border-b border-slate-700 flex items-center justify-between bg-slate-900/50">
              <h3 className="text-lg font-bold text-blue-400 uppercase tracking-widest flex items-center">
                <Users className="h-5 w-5 mr-2" />
                {editingItem ? '编辑人员' : '新增人员'}
              </h3>
              <button
                onClick={() => {
                  setShowPersonnelModal(false);
                  setEditingItem(null);
                }}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    人员ID
                  </label>
                  <input
                    type="text"
                    value={personnelForm.id}
                    onChange={e => setPersonnelForm({ ...personnelForm, id: e.target.value })}
                    placeholder="例如: EMP-001"
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    姓名/岗位
                  </label>
                  <input
                    type="text"
                    value={personnelForm.name}
                    onChange={e => setPersonnelForm({ ...personnelForm, name: e.target.value })}
                    placeholder="例如: 高级车工"
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  技能（逗号分隔）
                </label>
                <input
                  type="text"
                  value={personnelForm.skills}
                  onChange={e => setPersonnelForm({ ...personnelForm, skills: e.target.value })}
                  placeholder="例如: 车削, 铣削, 编程"
                  className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
                />
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    技能等级
                  </label>
                  <select
                    value={personnelForm.level}
                    onChange={e => setPersonnelForm({ ...personnelForm, level: e.target.value })}
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
                  >
                    <option value="junior">初级</option>
                    <option value="intermediate">中级</option>
                    <option value="senior">高级</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    班次
                  </label>
                  <select
                    value={personnelForm.shift}
                    onChange={e => setPersonnelForm({ ...personnelForm, shift: e.target.value })}
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
                  >
                    <option value="day">白班</option>
                    <option value="night">夜班</option>
                    <option value="rotating">轮班</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                    时薪 (¥/小时)
                  </label>
                  <input
                    type="number"
                    value={personnelForm.hourly_rate}
                    onChange={e =>
                      setPersonnelForm({
                        ...personnelForm,
                        hourly_rate: parseFloat(e.target.value) || 0,
                      })
                    }
                    className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
                  />
                </div>
              </div>
            </div>
            <div className="p-6 border-t border-slate-700 bg-slate-900/50 flex justify-end space-x-3">
              <button
                onClick={() => {
                  setShowPersonnelModal(false);
                  setEditingItem(null);
                }}
                className="px-6 py-2 border border-slate-600 text-slate-300 rounded-lg hover:bg-slate-800 transition-colors font-mono text-sm"
              >
                取消
              </button>
              <button
                onClick={handleAddPersonnel}
                className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-500 transition-colors font-mono text-sm font-bold tracking-wide shadow-[0_0_15px_rgba(59,130,246,0.3)]"
              >
                {editingItem ? '保存' : '添加'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 材料模态框 */}
      {showMaterialModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="glass-panel w-full max-w-md rounded-xl border border-slate-600 shadow-2xl">
            <div className="p-6 border-b border-slate-700 flex items-center justify-between bg-slate-900/50">
              <h3 className="text-lg font-bold text-green-400 uppercase tracking-widest flex items-center">
                <Package className="h-5 w-5 mr-2" />
                新增材料
              </h3>
              <button
                onClick={() => setShowMaterialModal(false)}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  材料名称
                </label>
                <input
                  type="text"
                  value={materialForm.name}
                  onChange={e => setMaterialForm({ ...materialForm, name: e.target.value })}
                  placeholder="例如: 45#钢"
                  className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-green-500 focus:border-green-500 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  单价 (¥/KG)
                </label>
                <input
                  type="number"
                  value={materialForm.price}
                  onChange={e =>
                    setMaterialForm({ ...materialForm, price: parseFloat(e.target.value) || 0 })
                  }
                  className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-green-500 focus:border-green-500 font-mono text-sm"
                />
              </div>
            </div>
            <div className="p-6 border-t border-slate-700 bg-slate-900/50 flex justify-end space-x-3">
              <button
                onClick={() => setShowMaterialModal(false)}
                className="px-6 py-2 border border-slate-600 text-slate-300 rounded-lg hover:bg-slate-800 transition-colors font-mono text-sm"
              >
                取消
              </button>
              <button
                onClick={handleAddMaterial}
                className="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-500 transition-colors font-mono text-sm font-bold tracking-wide shadow-[0_0_15px_rgba(34,197,94,0.3)]"
              >
                添加
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// 思考日志行组件
const ThinkingLogLine = React.memo(({ log }) => {
  if (log.type === 'title') {
    return (
      <div className="flex items-center text-cyan-400 font-bold border-t border-slate-800/50 pt-4 mt-2 font-mono uppercase tracking-wider">
        <span className="mr-2 text-cyan-500">➜</span>
        <span className="mr-3">STEP {log.step}:</span>
        <span className="typing-effect text-cyan-300">{log.content}</span>
      </div>
    );
  }

  if (log.type === 'thinking') {
    return (
      <div className="pl-6 text-slate-400 border-l border-slate-800 ml-1.5 my-1 font-mono text-xs">
        <span className="text-slate-600 mr-2">[{log.timestamp}]</span>
        <span className="text-slate-300">{log.content}</span>
      </div>
    );
  }

  if (log.type === 'start') {
    return (
      <div className="text-green-400 font-bold mb-2 font-mono flex items-center">
        <span className="mr-2 text-green-500 animate-pulse">⚡</span>
        <span className="tracking-widest">INITIALIZING_SYSTEM...</span>
      </div>
    );
  }

  if (log.type === 'step_complete') {
    return (
      <div className="pl-6 text-green-500/80 text-xs mb-2 font-mono flex items-center">
        <CheckCircle className="h-3 w-3 inline mr-2" />
        <span className="uppercase">STEP_{log.step}_COMPLETED</span>
      </div>
    );
  }

  if (log.type === 'complete') {
    return (
      <div className="text-green-400 font-bold mt-4 border-t border-green-500/30 pt-4 font-mono flex items-center bg-green-500/5 p-2 rounded">
        <CheckCircle className="h-4 w-4 mr-2" />
        <span className="tracking-widest">ANALYSIS_COMPLETE_SUCCESSFULLY</span>
      </div>
    );
  }

  if (log.type === 'error') {
    return (
      <div className="text-red-400 font-bold mt-2 bg-red-500/10 p-2 rounded border border-red-500/20 font-mono flex items-center">
        <AlertCircle className="h-4 w-4 mr-2" />
        <span>SYSTEM_ERROR: {log.content}</span>
      </div>
    );
  }

  if (log.type === 'debug') {
    return (
      <div className="pl-2 text-yellow-500/80 text-xs font-mono border-l-2 border-yellow-500/30 ml-1 my-1">
        <span>{log.content}</span>
      </div>
    );
  }

  return null;
});

export default App;
