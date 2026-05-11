import React from 'react';
import { Sparkles } from 'lucide-react';
import { Link } from 'react-router-dom';
import '../../styles/components/footer-modern.css';

const Footer = () => {
  const currentYear = new Date().getFullYear();

  // Only functional links
  const navLinks = [
    { label: 'Home', path: '/' },
    { label: 'Try On', path: '/try-on' },
  ];

  return (
    <footer className="footer">
      {/* Wave Decoration */}
      <div className="footer-wave">
        <svg 
          viewBox="0 0 1200 120" 
          preserveAspectRatio="none"
          className="wave-svg"
        >
          <path 
            d="M321.39,56.44c58-10.79,114.16-30.13,172-41.86,82.39-16.72,168.19-17.73,250.45-.39C823.78,31,906.67,72,985.66,92.83c70.05,18.48,146.53,26.09,214.34,3V0H0V27.35A600.21,600.21,0,0,0,321.39,56.44Z" 
            className="wave-path"
          ></path>
        </svg>
      </div>

      <div className="footer-content container">
        {/* Brand Section */}
        <div className="footer-brand">
          <div className="footer-logo">
            <Sparkles size={24} />
          </div>
          <h3 className="brand-title">StyleForge</h3>
          <p className="brand-tagline">
            AI-powered virtual try-on for fashion innovation
          </p>
        </div>

        {/* Navigation */}
        <nav className="footer-nav">
          {navLinks.map((link) => (
            <Link
              key={link.label}
              to={link.path}
              className="nav-link"
            >
              {link.label}
            </Link>
          ))}
        </nav>

        {/* Copyright - Updated to Data Science */}
        <div className="footer-bottom">
          <p className="copyright">
            © {currentYear} Final Year Project - Data Science
            <br />
            <small>Virtual Try-On System using AI & 3D Reconstruction</small>
          </p>
        </div>
      </div>
    </footer>
  );
};

export default Footer;