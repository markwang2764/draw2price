import React, { useState, useEffect, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';
import {
  Search,
  Plus,
  Upload,
  Trash2,
  Book,
  Wrench,
  Route,
  Clock,
  Shapes,
  ChevronDown,
  ChevronUp,
  FileText,
  CheckCircle,
  AlertCircle,
  Loader2,
  X,
} from 'lucide-react';

const API_BASE = '/api';

// 分类图标映射
const categoryIcons = {
  tool: Wrench,
  process_route: Route,
  cost: Clock,
  feature: Shapes,
};

// 分类颜色映射 (Tech Theme)
const categoryColors = {
  tool: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  process_route: 'bg-green-500/10 text-green-400 border-green-500/20',
  cost: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  feature: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
};

function KnowledgeManager() {
  const [stats, setStats] = useState({ count: 0, categories: {} });
  const [searchQuery, setSearchQuery] = useState('');
  const [searchCategory, setSearchCategory] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [expandedResult, setExpandedResult] = useState(null);
  const [notification, setNotification] = useState(null);
  const [allKnowledge, setAllKnowledge] = useState([]);
  const [isLoadingKnowledge, setIsLoadingKnowledge] = useState(false);
  const [expandedKnowledge, setExpandedKnowledge] = useState(null);
  const [activeCategory, setActiveCategory] = useState('all');

  // 新知识表单
  const [newKnowledge, setNewKnowledge] = useState({
    title: '',
    category: 'tool',
    content: '',
  });

  // 上传表单
  const [uploadForm, setUploadForm] = useState({
    file: null,
    category: 'tool',
    title: '',
  });

  // 加载统计信息
  const loadStats = async () => {
    try {
      const response = await axios.get(`${API_BASE}/knowledge/stats`);
      setStats(response.data);
    } catch (error) {
      console.error('加载统计失败:', error);
    }
  };

  // 加载所有知识数据
  const loadAllKnowledge = async () => {
    setIsLoadingKnowledge(true);
    try {
      const response = await axios.get(`${API_BASE}/knowledge/list`);
      setAllKnowledge(response.data.items || []);
    } catch (error) {
      console.error('加载知识数据失败:', error);
      // 如果API不存在，尝试使用搜索API获取所有数据
      try {
        const searchResponse = await axios.post(`${API_BASE}/knowledge/search`, {
          query: '',
          category: null,
          top_k: 100,
        });
        setAllKnowledge(searchResponse.data.results || []);
      } catch (e) {
        console.error('备用加载失败:', e);
      }
    } finally {
      setIsLoadingKnowledge(false);
    }
  };

  useEffect(() => {
    loadStats();
    loadAllKnowledge();
  }, []);

  // 搜索知识
  const handleSearch = async () => {
    if (!searchQuery.trim()) return;

    setIsSearching(true);
    try {
      const response = await axios.post(`${API_BASE}/knowledge/search`, {
        query: searchQuery,
        category: searchCategory || null,
        top_k: 10,
      });
      setSearchResults(response.data.results);
    } catch (error) {
      showNotification('搜索失败', 'error');
    } finally {
      setIsSearching(false);
    }
  };

  // 添加知识
  const handleAddKnowledge = async () => {
    if (!newKnowledge.title || !newKnowledge.content) {
      showNotification('请填写标题和内容', 'error');
      return;
    }

    try {
      await axios.post(`${API_BASE}/knowledge/add`, newKnowledge);
      showNotification('知识添加成功', 'success');
      setShowAddModal(false);
      setNewKnowledge({ title: '', category: 'tool', content: '' });
      loadStats();
    } catch (error) {
      showNotification('添加失败', 'error');
    }
  };

  // 文件上传处理
  const onDrop = useCallback(acceptedFiles => {
    if (acceptedFiles.length > 0) {
      const file = acceptedFiles[0];
      setUploadForm(prev => ({
        ...prev,
        file,
        title: prev.title || file.name.replace(/\.[^/.]+$/, ''),
      }));
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/plain': ['.txt'],
      'application/pdf': ['.pdf'],
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
    },
    maxFiles: 1,
  });

  // 上传文档
  const handleUpload = async () => {
    if (!uploadForm.file || !uploadForm.title) {
      showNotification('请选择文件并填写标题', 'error');
      return;
    }

    const formData = new FormData();
    formData.append('file', uploadForm.file);
    formData.append('category', uploadForm.category);
    formData.append('title', uploadForm.title);

    try {
      await axios.post(`${API_BASE}/knowledge/upload`, formData);
      showNotification('文档上传成功', 'success');
      setShowUploadModal(false);
      setUploadForm({ file: null, category: 'tool', title: '' });
      loadStats();
    } catch (error) {
      showNotification('上传失败: ' + (error.response?.data?.detail || '未知错误'), 'error');
    }
  };

  // 初始化知识库
  const handleInit = async () => {
    try {
      await axios.post(`${API_BASE}/knowledge/init`);
      showNotification('知识库初始化成功', 'success');
      loadStats();
    } catch (error) {
      showNotification('初始化失败', 'error');
    }
  };

  // 显示通知
  const showNotification = (message, type) => {
    setNotification({ message, type });
    setTimeout(() => setNotification(null), 3000);
  };

  return (
    <div className="space-y-6">
      {/* 通知 */}
      {notification && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-[0_0_20px_rgba(0,0,0,0.5)] flex items-center space-x-2 border animate-in fade-in slide-in-from-top-2 ${
            notification.type === 'success'
              ? 'bg-green-900/90 text-green-400 border-green-500/50'
              : 'bg-red-900/90 text-red-400 border-red-500/50'
          }`}
        >
          {notification.type === 'success' ? (
            <CheckCircle className="h-5 w-5" />
          ) : (
            <AlertCircle className="h-5 w-5" />
          )}
          <span className="font-mono text-sm">{notification.message}</span>
        </div>
      )}

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        <div className="glass-card rounded-xl p-6 border-l-4 border-l-cyan-500/50">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] text-cyan-500 uppercase tracking-widest mb-1">知识总量</p>
              <p className="text-3xl font-bold text-gray-100 font-mono">{stats.count}</p>
            </div>
            <div className="p-3 bg-cyan-500/10 rounded-lg">
              <Book className="h-8 w-8 text-cyan-400" />
            </div>
          </div>
        </div>

        {Object.entries(stats.categories || {}).map(([key, name]) => {
          const Icon = categoryIcons[key] || Book;
          const colorClass = categoryColors[key] || 'text-gray-400';
          // Extract text color from the utility class string for the icon
          const textColor =
            colorClass.split(' ').find(c => c.startsWith('text-')) || 'text-gray-400';
          // 获取该分类的数量
          const categoryCount = stats.category_counts?.[key] || 0;

          return (
            <div
              key={key}
              className={`glass-card rounded-xl p-6 border-l-4 ${colorClass
                .replace('bg-', 'border-l-')
                .split(' ')[0]
                .replace('/10', '/50')}`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                    {name}
                  </p>
                  <p className="text-3xl font-bold text-gray-100 font-mono">{categoryCount}</p>
                </div>
                <div className={`p-2 rounded-lg ${colorClass.split(' ')[0]}`}>
                  <Icon className={`h-6 w-6 ${textColor}`} />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* 操作按钮 */}
      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => setShowAddModal(true)}
          className="px-4 py-2 bg-blue-600/20 text-blue-400 border border-blue-500/50 rounded-lg hover:bg-blue-600/30 transition-all flex items-center space-x-2 group"
        >
          <Plus className="h-4 w-4 group-hover:scale-110 transition-transform" />
          <span className="font-mono text-sm tracking-wide">添加条目</span>
        </button>
        <button
          onClick={() => setShowUploadModal(true)}
          className="px-4 py-2 bg-green-600/20 text-green-400 border border-green-500/50 rounded-lg hover:bg-green-600/30 transition-all flex items-center space-x-2 group"
        >
          <Upload className="h-4 w-4 group-hover:-translate-y-0.5 transition-transform" />
          <span className="font-mono text-sm tracking-wide">上传文档</span>
        </button>
        <button
          onClick={handleInit}
          className="px-4 py-2 bg-slate-700/50 text-slate-300 border border-slate-600 rounded-lg hover:bg-slate-700 transition-all flex items-center space-x-2"
        >
          <Book className="h-4 w-4" />
          <span className="font-mono text-sm tracking-wide">重置数据库</span>
        </button>
      </div>

      {/* 搜索区域 */}
      <div className="glass-card rounded-xl p-6 border border-slate-700/50">
        <h2 className="text-sm font-bold mb-4 flex items-center text-cyan-400 uppercase tracking-widest">
          <Search className="h-4 w-4 mr-2" />
          知识检索
        </h2>
        <div className="flex flex-wrap gap-3">
          <div className="flex-1 relative group">
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyPress={e => e.key === 'Enter' && handleSearch()}
              placeholder="输入搜索关键词..."
              className="w-full pl-4 pr-4 py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm transition-all"
            />
            <div className="absolute inset-0 rounded-lg bg-cyan-500/5 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity"></div>
          </div>
          <select
            value={searchCategory}
            onChange={e => setSearchCategory(e.target.value)}
            className="px-4 py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-300 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
          >
            <option value="">所有分类</option>
            {Object.entries(stats.categories || {}).map(([key, name]) => (
              <option key={key} value={key}>
                {name.toUpperCase()}
              </option>
            ))}
          </select>
          <button
            onClick={handleSearch}
            disabled={isSearching}
            className="px-6 py-2.5 bg-cyan-500/20 text-cyan-400 border border-cyan-500/50 rounded-lg hover:bg-cyan-500/30 disabled:opacity-50 disabled:cursor-not-allowed flex items-center space-x-2 transition-all shadow-[0_0_15px_rgba(6,182,212,0.1)] hover:shadow-[0_0_20px_rgba(6,182,212,0.2)]"
          >
            {isSearching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            <span className="font-mono font-bold tracking-wide">搜索</span>
          </button>
        </div>

        {/* 搜索结果 */}
        {searchResults.length > 0 && (
          <div className="mt-6 space-y-3">
            <div className="flex justify-between items-center border-b border-slate-700 pb-2 mb-4">
              <h3 className="font-mono text-xs text-slate-500 uppercase tracking-widest">
                搜索结果
              </h3>
              <span className="font-mono text-xs text-cyan-500 bg-cyan-900/20 px-2 py-0.5 rounded border border-cyan-900/50">
                找到 {searchResults.length} 条
              </span>
            </div>
            {searchResults.map((result, index) => (
              <div
                key={index}
                className="border border-slate-700/50 rounded-lg overflow-hidden transition-all hover:border-cyan-500/30 hover:shadow-[0_0_15px_rgba(0,0,0,0.2)]"
              >
                <div
                  className="p-4 bg-slate-800/40 cursor-pointer flex items-center justify-between hover:bg-slate-800/60"
                  onClick={() => setExpandedResult(expandedResult === index ? null : index)}
                >
                  <div className="flex items-center space-x-3 overflow-hidden">
                    <span
                      className={`px-2 py-1 text-[10px] rounded border font-mono uppercase whitespace-nowrap ${
                        categoryColors[result.metadata?.category] ||
                        'bg-slate-700/50 text-slate-400 border-slate-600'
                      }`}
                    >
                      {stats.categories?.[result.metadata?.category] ||
                        result.metadata?.category ||
                        'UNKNOWN'}
                    </span>
                    <span className="font-bold text-slate-200 truncate">
                      {result.metadata?.title}
                    </span>
                    <span className="text-[10px] text-slate-500 font-mono whitespace-nowrap">
                      相关度: {(result.relevance * 100).toFixed(0)}%
                    </span>
                  </div>
                  {expandedResult === index ? (
                    <ChevronUp className="h-5 w-5 text-cyan-500" />
                  ) : (
                    <ChevronDown className="h-5 w-5 text-slate-500" />
                  )}
                </div>
                {expandedResult === index && (
                  <div className="p-4 bg-slate-900/80 border-t border-slate-700">
                    <div className="font-mono text-xs text-slate-400 whitespace-pre-wrap leading-relaxed">
                      {result.content}
                    </div>
                    {result.metadata?.source && (
                      <div className="mt-3 pt-3 border-t border-slate-800 text-[10px] text-slate-600 font-mono">
                        来源: {result.metadata.source}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 知识库数据结构化显示 */}
      <div className="glass-card rounded-xl p-6 border border-slate-700/50">
        <div className="flex items-center justify-between mb-6 border-b border-slate-700 pb-4">
          <h2 className="text-sm font-bold flex items-center text-cyan-400 uppercase tracking-widest">
            <Book className="h-4 w-4 mr-2" />
            知识库内容
          </h2>
          <div className="flex items-center gap-2">
            <select
              value={activeCategory}
              onChange={e => setActiveCategory(e.target.value)}
              className="px-3 py-1.5 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-300 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-xs"
            >
              <option value="all">全部分类</option>
              {Object.entries(stats.categories || {}).map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
            <button
              onClick={() => {
                loadAllKnowledge();
                loadStats();
              }}
              className="p-1.5 hover:bg-cyan-500/10 rounded transition-colors text-slate-500 hover:text-cyan-400"
              title="刷新"
            >
              <Loader2 className={`h-4 w-4 ${isLoadingKnowledge ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {isLoadingKnowledge ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-cyan-400" />
            <span className="ml-3 text-slate-400 font-mono text-sm">加载中...</span>
          </div>
        ) : allKnowledge.length === 0 ? (
          <div className="text-center py-12">
            <Book className="h-12 w-12 text-slate-600 mx-auto mb-4" />
            <p className="text-slate-500 font-mono text-sm">暂无知识数据</p>
            <p className="text-slate-600 font-mono text-xs mt-2">
              点击"添加条目"或"上传文档"添加知识
            </p>
          </div>
        ) : (
          <div className="space-y-3 max-h-[500px] overflow-y-auto">
            {allKnowledge
              .filter(
                item =>
                  activeCategory === 'all' ||
                  (item.metadata?.category || item.category) === activeCategory
              )
              .map((item, index) => {
                const category = item.metadata?.category || item.category || 'unknown';
                const title = item.metadata?.title || item.title || '未命名';
                const content = item.content || item.text || '';
                const Icon = categoryIcons[category] || Book;
                const colorClass =
                  categoryColors[category] || 'bg-slate-700/50 text-slate-400 border-slate-600';

                return (
                  <div
                    key={index}
                    className="border border-slate-700/50 rounded-lg overflow-hidden transition-all hover:border-cyan-500/30"
                  >
                    <div
                      className="p-4 bg-slate-800/40 cursor-pointer flex items-center justify-between hover:bg-slate-800/60"
                      onClick={() =>
                        setExpandedKnowledge(expandedKnowledge === index ? null : index)
                      }
                    >
                      <div className="flex items-center space-x-3 overflow-hidden">
                        <div className={`p-2 rounded-lg ${colorClass.split(' ')[0]}`}>
                          <Icon
                            className={`h-4 w-4 ${
                              colorClass.split(' ').find(c => c.startsWith('text-')) ||
                              'text-slate-400'
                            }`}
                          />
                        </div>
                        <div className="overflow-hidden">
                          <span className="font-bold text-slate-200 block truncate">{title}</span>
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded border font-mono uppercase ${colorClass}`}
                          >
                            {stats.categories?.[category] || category}
                          </span>
                        </div>
                      </div>
                      {expandedKnowledge === index ? (
                        <ChevronUp className="h-5 w-5 text-cyan-500 flex-shrink-0" />
                      ) : (
                        <ChevronDown className="h-5 w-5 text-slate-500 flex-shrink-0" />
                      )}
                    </div>
                    {expandedKnowledge === index && (
                      <div className="p-4 bg-slate-900/80 border-t border-slate-700">
                        <div className="font-mono text-xs text-slate-400 whitespace-pre-wrap leading-relaxed max-h-[300px] overflow-y-auto">
                          {content}
                        </div>
                        {item.metadata?.source && (
                          <div className="mt-3 pt-3 border-t border-slate-800 text-[10px] text-slate-600 font-mono">
                            来源: {item.metadata.source}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        )}
      </div>

      {/* 添加知识模态框 */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="glass-panel w-full max-w-2xl max-h-[90vh] overflow-auto rounded-xl border border-slate-600 shadow-2xl">
            <div className="p-6 border-b border-slate-700 flex items-center justify-between bg-slate-900/50">
              <h3 className="text-lg font-bold text-cyan-400 uppercase tracking-widest flex items-center">
                <Plus className="h-5 w-5 mr-2" />
                添加知识条目
              </h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
            <div className="p-6 space-y-5">
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  条目标题
                </label>
                <input
                  type="text"
                  value={newKnowledge.title}
                  onChange={e => setNewKnowledge({ ...newKnowledge, title: e.target.value })}
                  placeholder="例如: TC4钛合金加工参数"
                  className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  分类
                </label>
                <select
                  value={newKnowledge.category}
                  onChange={e => setNewKnowledge({ ...newKnowledge, category: e.target.value })}
                  className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm"
                >
                  {Object.entries(stats.categories || {}).map(([key, name]) => (
                    <option key={key} value={key}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  内容数据
                </label>
                <textarea
                  value={newKnowledge.content}
                  onChange={e => setNewKnowledge({ ...newKnowledge, content: e.target.value })}
                  rows={12}
                  placeholder="// 在此输入知识数据..."
                  className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500 font-mono text-sm leading-relaxed"
                />
              </div>
            </div>
            <div className="p-6 border-t border-slate-700 bg-slate-900/50 flex justify-end space-x-3">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-6 py-2 border border-slate-600 text-slate-300 rounded-lg hover:bg-slate-800 transition-colors font-mono text-sm"
              >
                取消
              </button>
              <button
                onClick={handleAddKnowledge}
                className="px-6 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-500 transition-colors font-mono text-sm font-bold tracking-wide shadow-[0_0_15px_rgba(6,182,212,0.3)]"
              >
                保存条目
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 上传文档模态框 */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="glass-panel w-full max-w-lg rounded-xl border border-slate-600 shadow-2xl">
            <div className="p-6 border-b border-slate-700 flex items-center justify-between bg-slate-900/50">
              <h3 className="text-lg font-bold text-green-400 uppercase tracking-widest flex items-center">
                <Upload className="h-5 w-5 mr-2" />
                上传文档
              </h3>
              <button
                onClick={() => setShowUploadModal(false)}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
            <div className="p-6 space-y-5">
              <div
                {...getRootProps()}
                className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
                  isDragActive
                    ? 'border-green-500 bg-green-500/10'
                    : uploadForm.file
                    ? 'border-green-500/50 bg-green-500/5'
                    : 'border-slate-600 hover:border-green-500/50 hover:bg-slate-800'
                }`}
              >
                <input {...getInputProps()} />
                {uploadForm.file ? (
                  <div className="text-green-400">
                    <FileText className="h-12 w-12 mx-auto mb-3" />
                    <p className="font-mono font-bold text-sm truncate">{uploadForm.file.name}</p>
                    <p className="text-xs text-green-500/70 mt-2 font-mono">点击替换</p>
                  </div>
                ) : (
                  <div className="text-slate-400">
                    <Upload className="h-12 w-12 mx-auto mb-3" />
                    <p className="font-medium text-sm">拖放或点击上传</p>
                    <p className="text-[10px] mt-2 font-mono uppercase text-slate-500">
                      支持: PDF, Word, TXT
                    </p>
                  </div>
                )}
              </div>
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  文档标题
                </label>
                <input
                  type="text"
                  value={uploadForm.title}
                  onChange={e => setUploadForm({ ...uploadForm, title: e.target.value })}
                  placeholder="例如: 标准操作规程 2024"
                  className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-600 focus:ring-1 focus:ring-green-500 focus:border-green-500 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-mono text-slate-400 mb-2 uppercase">
                  分类
                </label>
                <select
                  value={uploadForm.category}
                  onChange={e => setUploadForm({ ...uploadForm, category: e.target.value })}
                  className="w-full px-4 py-3 bg-slate-900/50 border border-slate-700 rounded-lg text-slate-200 focus:ring-1 focus:ring-green-500 focus:border-green-500 font-mono text-sm"
                >
                  {Object.entries(stats.categories || {}).map(([key, name]) => (
                    <option key={key} value={key}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="p-6 border-t border-slate-700 bg-slate-900/50 flex justify-end space-x-3">
              <button
                onClick={() => setShowUploadModal(false)}
                className="px-6 py-2 border border-slate-600 text-slate-300 rounded-lg hover:bg-slate-800 transition-colors font-mono text-sm"
              >
                取消
              </button>
              <button
                onClick={handleUpload}
                className="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-500 transition-colors font-mono text-sm font-bold tracking-wide shadow-[0_0_15px_rgba(34,197,94,0.3)]"
              >
                开始上传
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default KnowledgeManager;
