import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import {
  Upload, Settings, Eye, Box, RotateCw,
  Download, Share2, CheckCircle, AlertCircle, Clock, Maximize2,
} from 'lucide-react';

import Button from '../components/common/Button';
import Card from '../components/common/Card';
import FileUploader from '../components/upload/FileUploader';
import TextInput from '../components/upload/TextInput';
import AttributesForm from '../components/upload/AttributesForm';
import ModelViewer from '../components/viewer/ModelViewer';
import Modal from '../components/common/Modal';
import { tryOn2D, tryOn3D } from '../api/tryon';
import usePolling from '../hooks/usePolling';
import { JOB_STATUS } from '../utils/constants';
import '../styles/pages/tryon.css';

// ── Helper: extract File from whatever FileUploader returns ──────────────────
const extractFile = (imageData) => {
  if (!imageData) return null;
  if (imageData instanceof File)       return imageData;
  if (imageData.file instanceof File)  return imageData.file;
  if (imageData.rawFile instanceof File) return imageData.rawFile;
  if (imageData.originalFile instanceof File) return imageData.originalFile;
  // Last resort: check all keys for a File
  for (const key of Object.keys(imageData)) {
    if (imageData[key] instanceof File) return imageData[key];
  }
  return null;
};

const TryOn = () => {
  const navigate = useNavigate();

  const [userImage, setUserImage]                 = useState(null);
  const [garmentImage, setGarmentImage]           = useState(null);
  const [instruction, setInstruction]             = useState('');
  const [attributes, setAttributes]               = useState({});
  const [isGenerating2D, setIsGenerating2D]       = useState(false);
  const [isGenerating3D, setIsGenerating3D]       = useState(false);
  const [result2D, setResult2D]                   = useState(null);
  const [result3D, setResult3D]                   = useState(null);
  const [activeTab, setActiveTab]                 = useState('upload');
  const [jobId2D, setJobId2D]                     = useState(null);
  const [jobId3D, setJobId3D]                     = useState(null);
  const [show3DViewer, setShow3DViewer]           = useState(false);
  const [showAttributes, setShowAttributes]       = useState(false);
  const [sessionId]                               = useState(
    () => `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  );
  const [hasShown2DSuccess, setHasShown2DSuccess] = useState(false);
  const [hasShown3DSuccess, setHasShown3DSuccess] = useState(false);
  const [outputId2D, setOutputId2D]               = useState(null);  // output_id from 2D for 3D lookup

  const { status: status2D, isPolling: isPolling2D } = usePolling(jobId2D, (data) => {
    if (data.status === JOB_STATUS.COMPLETED && data.result?.preview_url) {
      setResult2D(data.result.preview_url);
      setIsGenerating2D(false);
      setActiveTab('preview');
      if (!hasShown2DSuccess) { toast.success('2D preview generated!'); setHasShown2DSuccess(true); }
    } else if (data.status === JOB_STATUS.FAILED) {
      setIsGenerating2D(false);
      toast.error('2D generation failed');
    }
  }, { interval: 2000, maxAttempts: 150 });  // 2D: up to 5 min

  const { status: status3D, isPolling: isPolling3D } = usePolling(jobId3D, (data) => {
    if (data.status === JOB_STATUS.COMPLETED && data.result?.download_url) {
      setResult3D(data.result.download_url);
      setIsGenerating3D(false);
      setActiveTab('3d');
      if (!hasShown3DSuccess) { toast.success('3D model generated!'); setHasShown3DSuccess(true); }
    } else if (data.status === JOB_STATUS.FAILED) {
      setIsGenerating3D(false);
      toast.error('3D generation failed');
    }
  }, { interval: 5000, maxAttempts: 360 });  // 3D: every 5s, up to 30 min

  useEffect(() => { if (isGenerating2D) setHasShown2DSuccess(false); }, [isGenerating2D]);
  useEffect(() => { if (isGenerating3D) setHasShown3DSuccess(false); }, [isGenerating3D]);

  const handleUserImageSelect = (fileData) => {
    if (fileData) { setUserImage(fileData); setActiveTab('configure'); }
  };

  const handleGarmentImageSelect = (fileData) => { setGarmentImage(fileData); };

  const handleAttributesChange = (newAttributes) => {
    setAttributes(newAttributes);
    if (newAttributes.generated_instruction) setInstruction(newAttributes.generated_instruction);
  };

  // ── FIXED handleGenerate2D ────────────────────────────────────────────────
  const handleGenerate2D = async () => {
    if (isGenerating2D) return;

    if (!userImage) { toast.error('Please upload your photo first'); return; }
    if (!instruction.trim()) { toast.error('Please describe what you want to wear'); return; }

    setIsGenerating2D(true);
    setResult2D(null);
    setResult3D(null);
    setJobId3D(null);

    const fullInstruction = attributes.garment_type
      ? `${instruction} (${Object.entries(attributes)
          .filter(([k, v]) => v && k !== 'generated_instruction')
          .map(([k, v]) => `${k}: ${v}`).join(', ')})`
      : instruction;

    try {
      // ✅ Extract actual File object from whatever FileUploader returned
      const personFile  = extractFile(userImage);
      const garmentFile = extractFile(garmentImage);

      console.log('personFile:', personFile);
      console.log('garmentFile:', garmentFile);

      if (!personFile) {
        toast.error('Could not read image. Please re-upload your photo.');
        setIsGenerating2D(false);
        return;
      }

      // ✅ Pass as object — matches what tryon.js createFormData expects
      const response = await tryOn2D({
        user_image:        personFile,
        instruction:       fullInstruction.trim(),
        garment_reference: garmentFile || undefined,
        session_id:        sessionId,
      });

      const d = response.data;
      console.log('Response data:', d);

      // Save output_id for the 3D pipeline (it uses this to find the 2D result PNG)
      if (d.output_id) setOutputId2D(d.output_id);

      // ✅ Check all possible keys backend might return
      const resultImage =
        d.result_image  ||
        d.image_base64  ||
        d.preview_url   ||
        d.output_image  ||
        null;

      if (resultImage) {
        setResult2D(resultImage);
        setActiveTab('preview');
        toast.success('2D preview generated!');
      } else if (d.job_id) {
        setJobId2D(d.job_id);
        toast.success('2D generation started!');
      } else {
        toast.error('No image returned from server.');
      }
    } catch (error) {
      console.error('Error generating 2D:', error);
      const msg =
        error?.response?.data?.detail ||
        error?.apiError?.message ||
        error?.message ||
        'Failed to generate 2D preview';
      toast.error(msg);
    } finally {
      setIsGenerating2D(false);
    }
  };

  const handleGenerate3D = async () => {
    if (isGenerating3D) return;
    if (!result2D) { toast.error('Please generate 2D preview first'); return; }

    setIsGenerating3D(true);
    setResult3D(null);

    try {
      const personFile = extractFile(userImage);
      const response = await tryOn3D({
        user_image:  personFile,
        output_id:   outputId2D,           // ← 3D service uses this to find the 2D result PNG
        instruction: instruction.trim(),
        session_id:  sessionId,
      });

      const d = response.data;
      // If the 3D service returns a download_url directly (synchronous), use it
      if (d.download_url && d.status === 'completed') {
        setResult3D(d.download_url);
        setIsGenerating3D(false);
        setActiveTab('3d');
        toast.success('3D model generated!');
      } else if (d.job_id) {
        // Async: pipeline running in background, polling takes over
        setJobId3D(d.job_id);
        setIsGenerating3D(false);  // let isPolling3D drive the spinner
        toast.success('3D generation started! First run may take 10-15 min.');
      } else {
        toast.error('Unexpected response from 3D service');
        setIsGenerating3D(false);
      }
    } catch (error) {
      console.error('Error generating 3D:', error);
      const msg =
        error?.response?.data?.detail ||
        error?.apiError?.message ||
        error?.message ||
        'Failed to start 3D generation';
      toast.error(msg);
      setIsGenerating3D(false);
    }
  };

  const handleDownload = async (type) => {
    const url = type === '2d' ? result2D : result3D;
    const ext = type === '2d' ? 'png' : 'glb';
    if (!url) return;
    try {
      const res  = await fetch(url);
      const blob = await res.blob();
      const link = document.createElement('a');
      link.href     = window.URL.createObjectURL(blob);
      link.download = `styleforge_${type}_${Date.now()}.${ext}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(link.href);
      toast.success(`${type.toUpperCase()} downloaded!`);
    } catch { toast.error('Failed to download'); }
  };

  const handleReset = () => {
    setUserImage(null); setGarmentImage(null); setInstruction(''); setAttributes({});
    setResult2D(null); setResult3D(null); setJobId2D(null); setJobId3D(null);
    setActiveTab('upload'); setHasShown2DSuccess(false); setHasShown3DSuccess(false);
    toast('All inputs cleared');
  };

  const tabs = [
    { id: 'upload',    label: 'Upload',    icon: Upload,   visible: true },
    { id: 'configure', label: 'Configure', icon: Settings, visible: !!userImage },
    { id: 'preview',   label: 'Preview',   icon: Eye,      visible: !!result2D },
    { id: '3d',        label: '3D View',   icon: Box,      visible: !!result3D },
  ];

  const isLoading2D = isGenerating2D || isPolling2D;
  const isLoading3D = isGenerating3D || isPolling3D;

  return (
    <div className="tryon-page">
      <div className="tryon-header">
        <div className="container">
          <h1 className="tryon-title">Virtual Try-On</h1>
          <p className="tryon-subtitle">Upload your photo, describe your outfit, and see the magic</p>
        </div>
      </div>

      <div className="tryon-container container">
        <div className="tryon-layout">

          {/* Left Panel */}
          <div className="tryon-configuration">
            <Card title="Try-On Configuration">
              <div className="progress-steps">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    className={`progress-step ${activeTab === tab.id ? 'active' : ''} ${tab.visible ? '' : 'disabled'}`}
                    onClick={() => tab.visible && setActiveTab(tab.id)}
                    disabled={!tab.visible}
                  >
                    <div className="step-icon"><tab.icon size={20} /></div>
                    <div className="step-label">{tab.label}</div>
                  </button>
                ))}
              </div>

              <div className="tab-content">
                {activeTab === 'upload' && (
                  <div className="upload-tab">
                    <h3>Upload Your Photo</h3>
                    <p>Start by uploading a clear front-facing photo</p>
                    <FileUploader label="User Photo" description="Upload your photo" onFileSelect={handleUserImageSelect} value={userImage} required />
                    <div className="upload-guidelines">
                      <h4>Guidelines:</h4>
                      <ul>
                        <li>Front-facing upper body photo</li>
                        <li>Good lighting conditions</li>
                        <li>Plain background recommended</li>
                        <li>Arms visible by your sides</li>
                      </ul>
                    </div>
                  </div>
                )}

                {activeTab === 'configure' && (
                  <div className="configure-tab">
                    <div className="image-preview-container">
                      <img src={userImage?.previewUrl} alt="User preview" className="user-preview-image" />
                    </div>
                    <div className="instruction-section">
                      <div className="section-header">
                        <h4>Describe Your Outfit</h4>
                        <Button variant="ghost" size="small" onClick={() => setShowAttributes(true)}>Use Attributes</Button>
                      </div>
                      <TextInput value={instruction} onChange={setInstruction} placeholder="Describe what you want to wear..." label="Outfit Description" required rows={3} />
                    </div>
                    <div className="garment-reference">
                      <h4>Reference Garment</h4>
                      <FileUploader label="" description="Upload garment reference" onFileSelect={handleGarmentImageSelect} value={garmentImage} showPreview={false} />
                    </div>
                    <Button onClick={handleGenerate2D} loading={isLoading2D} disabled={!instruction.trim() || isLoading2D} fullWidth size="large">
                      {isLoading2D ? 'Generating 2D...' : 'Generate 2D Preview'}
                    </Button>
                  </div>
                )}

                {activeTab === 'preview' && (
                  <div className="preview-tab">
                    <div className="preview-header">
                      <h3>2D Preview</h3>
                    </div>
                    <div className="preview-image-wrapper">
                      {result2D && <img src={result2D} alt="2D try-on result" />}
                    </div>
                    <div className="preview-actions">
                      <Button variant="outline" onClick={() => setActiveTab('configure')} icon={RotateCw}>Edit</Button>
                      <Button variant="outline" onClick={() => handleDownload('2d')} icon={Download}>Download</Button>
                      <Button onClick={handleGenerate3D} loading={isLoading3D} disabled={isLoading3D} icon={Box}>Generate 3D</Button>
                    </div>
                  </div>
                )}

                {activeTab === '3d' && (
                  <div className="three-d-tab">
                    <div className="model-header"><h3>3D Model</h3></div>
                    <div className="model-info">
                      <div className="info-item"><Clock size={16} /><span>Status: {status3D?.status || 'Ready'}</span></div>
                      <div className="info-item"><CheckCircle size={16} /><span>Format: GLB</span></div>
                    </div>
                    <div className="model-actions">
                      <Button variant="outline" onClick={() => handleDownload('3d')} icon={Download} fullWidth>Download 3D Model</Button>
                      <Button variant="outline" onClick={() => setShow3DViewer(true)} icon={Maximize2} fullWidth>View in 3D Viewer</Button>
                      <Button variant="outline" onClick={() => { navigator.clipboard.writeText(window.location.href); toast.success('Link copied!'); }} icon={Share2} fullWidth>Share Result</Button>
                    </div>
                  </div>
                )}
              </div>

              <div className="reset-section">
                <Button variant="ghost" onClick={handleReset} icon={RotateCw}>Start Over</Button>
              </div>
            </Card>
          </div>

          {/* Right Panel */}
          <div className="tryon-preview">
            <Card title="Live Preview">
              <div className="preview-area">
                {isLoading2D || isLoading3D ? (
                  <div className="loading-overlay">
                    <div className="loading-spinner"></div>
                    <h3>{isLoading2D ? 'Generating 2D Preview...' : 'Generating 3D Model...'}</h3>
                    <p>{isLoading3D
                      ? (isPolling3D
                          ? `Processing... (${status3D?.status || 'in queue'})`
                          : 'Submitting job...')
                      : 'This may take a few moments'}</p>
                    {isLoading3D && <p style={{fontSize:'0.8em', opacity:0.6, marginTop:'8px'}}>First run: ~10 min &bull; Subsequent: ~2 min</p>}
                  </div>
                ) : result2D ? (
                  <div className="result-preview">
                    <img src={result2D} alt="Try-on result" />
                    <div className="result-overlay">
                      <span className="result-badge">{result3D ? '3D Ready' : '2D Preview'}</span>
                    </div>
                  </div>
                ) : userImage ? (
                  <div className="user-preview-area">
                    <img src={userImage.previewUrl} alt="User photo" />
                    <div className="preview-message">
                      <p>Ready for generation</p>
                      <p className="subtext">Click "Generate 2D Preview" to continue</p>
                    </div>
                  </div>
                ) : (
                  <div className="empty-preview">
                    <Upload size={48} />
                    <p>Upload a photo to begin</p>
                  </div>
                )}
              </div>

              <div className="status-bar">
                {isLoading2D && <div className="status-item"><AlertCircle size={16} /><span>2D Generation in progress...</span></div>}
                {isLoading3D && <div className="status-item"><AlertCircle size={16} /><span>3D Generation in progress...</span></div>}
                {result2D && !isLoading2D && <div className="status-item success"><CheckCircle size={16} /><span>2D Preview ready</span></div>}
                {result3D && !isLoading3D && <div className="status-item success"><CheckCircle size={16} /><span>3D Model ready</span></div>}
              </div>
            </Card>
          </div>

        </div>
      </div>

      <Modal isOpen={showAttributes} onClose={() => setShowAttributes(false)} title="Garment Attributes" size="large">
        <AttributesForm onAttributesChange={handleAttributesChange} initialValues={attributes} />
        <div className="modal-actions">
          <Button onClick={() => { if (attributes.generated_instruction) { setInstruction(attributes.generated_instruction); toast.success('Instruction updated!'); } setShowAttributes(false); }}>Apply Attributes</Button>
          <Button variant="outline" onClick={() => setShowAttributes(false)}>Cancel</Button>
        </div>
      </Modal>

      <Modal isOpen={show3DViewer} onClose={() => setShow3DViewer(false)} title="3D Model Viewer" size="xlarge">
        {result3D && <ModelViewer modelUrl={result3D} onClose={() => setShow3DViewer(false)} />}
      </Modal>
    </div>
  );
};

export default TryOn;
