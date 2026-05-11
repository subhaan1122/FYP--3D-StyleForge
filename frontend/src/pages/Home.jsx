import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Upload, 
  Sparkles, 
  Zap, 
  Shield, 
  Palette,
  TrendingUp,
  Globe,
  ArrowRight,
  CheckCircle
} from 'lucide-react';
import Button from '../components/common/Button';
import Card from '../components/common/Card';
import '../styles/pages/home.css';

const Home = () => {
  const navigate = useNavigate();
  const [isDragging, setIsDragging] = useState(false);

  const features = [
    {
      icon: <Sparkles />,
      title: 'AI-Powered Design',
      description: 'Generate realistic outfits with cutting-edge AI models.',
      color: 'var(--color-primary-500)',
    },
    {
      icon: <Zap />,
      title: 'Real-Time Preview',
      description: 'See instant 2D previews and detailed 3D models.',
      color: 'var(--color-secondary-500)',
    },
    {
      icon: <Palette />,
      title: 'Style Customization',
      description: 'Customize colors, patterns, and styles with text prompts.',
      color: 'var(--color-success)',
    },
    {
      icon: <TrendingUp />,
      title: 'Perfect Fit',
      description: 'Intelligent garment fitting based on body measurements.',
      color: 'var(--color-warning)',
    },
    {
      icon: <Shield />,
      title: 'Privacy Focused',
      description: 'Your images are processed securely and never stored.',
      color: 'var(--color-info)',
    },
    {
      icon: <Globe />,
      title: 'Cross-Platform',
      description: 'Access from any device with a modern web browser.',
      color: 'var(--color-secondary-600)',
    },
  ];

  const processSteps = [
    {
      number: '01',
      title: 'Upload Your Photo',
      description: 'Upload a clear front-facing photo with good lighting.',
      icon: '📸',
    },
    {
      number: '02',
      title: 'Describe Your Style',
      description: 'Tell us what you want to wear using natural language.',
      icon: '💬',
    },
    {
      number: '03',
      title: 'Preview in 2D',
      description: 'See the outfit on yourself with instant 2D visualization.',
      icon: '👁️',
    },
    {
      number: '04',
      title: 'Generate 3D Model',
      description: 'Create a full 3D model to view from any angle.',
      icon: '🎮',
    },
  ];

  const handleGetStarted = () => {
    navigate('/try-on');
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      navigate('/try-on', { state: { uploadedImage: URL.createObjectURL(file) } });
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  return (
    <div className="home-page">
      {/* Hero Section */}
      <section className="hero-section">
        <div className="hero-background">
          <div className="hero-gradient"></div>
          <div className="hero-particles"></div>
        </div>
        
        <div className="container">
          <div className="hero-content">
            <div className="hero-badge">
              <Sparkles size={16} />
              <span>AI-Powered Fashion Technology</span>
            </div>
            
            <h1 className="hero-title fade-in">
              Experience Fashion in
              <span className="gradient-text"> Augmented Reality</span>
            </h1>
            
            <p className="hero-description slide-up">
              Transform your shopping experience with AI-powered virtual try-on. 
              See how clothes look on you before buying, with photorealistic 
              previews and interactive 3D models.
            </p>
            
            <div className="hero-actions slide-up">
              <Button
                size="large"
                onClick={handleGetStarted}
                icon={ArrowRight}
                iconPosition="right"
                className="hero-button"
              >
                Start Creating
              </Button>
              
              {/* Upload Zone */}
              <div
                className={`upload-zone ${isDragging ? 'dragging' : ''}`}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onClick={() => document.getElementById('file-input').click()}
              >
                <input
                  id="file-input"
                  type="file"
                  accept="image/*"
                  onChange={(e) => {
                    const file = e.target.files[0];
                    if (file) {
                      navigate('/try-on', { state: { uploadedImage: URL.createObjectURL(file) } });
                    }
                  }}
                  style={{ display: 'none' }}
                />
                
                <div className="upload-content">
                  <div className="upload-icon-wrapper">
                    <Upload size={32} />
                  </div>
                  <div className="upload-text-content">
                    <p className="upload-title">
                      {isDragging ? 'Drop to upload' : 'Drag & drop your photo'}
                    </p>
                    <p className="upload-subtitle">
                      or click to select file • JPG, PNG up to 10MB
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Process Section */}
      <section className="process-section">
        <div className="container">
          <div className="section-header scale-in">
            <h2 className="section-title">
              How It <span className="gradient-text">Works</span>
            </h2>
            <p className="section-description">
              Simple steps to transform your fashion experience
            </p>
          </div>

          <div className="process-steps">
            {processSteps.map((step, index) => (
              <div key={step.number} className="process-step fade-in" style={{ animationDelay: `${index * 0.1}s` }}>
                <div className="step-number">{step.number}</div>
                <div className="step-icon">{step.icon}</div>
                <div className="step-content">
                  <h3 className="step-title">{step.title}</h3>
                  <p className="step-description">{step.description}</p>
                </div>
                {index < processSteps.length - 1 && (
                  <div className="step-connector">
                    <ArrowRight size={20} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="features-section">
        <div className="container">
          <div className="section-header scale-in">
            <h2 className="section-title">
              Why Choose <span className="gradient-text">StyleForge</span>
            </h2>
            <p className="section-description">
              Advanced features for the perfect virtual try-on experience
            </p>
          </div>

          <div className="features-grid">
            {features.map((feature, index) => (
              <Card key={index} className="feature-card fade-in" style={{ animationDelay: `${index * 0.1}s` }}>
                <div 
                  className="feature-icon-wrapper"
                  style={{ '--icon-color': feature.color }}
                >
                  {feature.icon}
                </div>
                <h3 className="feature-title">{feature.title}</h3>
                <p className="feature-description">{feature.description}</p>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <div className="cta-background">
          <div className="cta-gradient"></div>
        </div>
        
        <div className="container">
          <div className="cta-content scale-in">
            <div className="cta-text">
              <h2 className="cta-title">
                Ready to Transform Your Fashion Experience?
              </h2>
              <p className="cta-description">
                Join the future of fashion technology and experience virtual 
                try-on like never before.
              </p>
            </div>
            
            <div className="cta-actions">
              <Button
                size="large"
                onClick={handleGetStarted}
                icon={Sparkles}
                className="cta-button"
              >
                Start Now
              </Button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

export default Home;