import React, { useRef, useEffect, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader';
import { Box, RotateCw, ZoomIn, ZoomOut, Download, Maximize2, Sun, Moon } from 'lucide-react';
import Button from '../common/Button';
import '../../styles/components/model-viewer.css';

const ModelViewer = ({ modelUrl, onClose }) => {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const rendererRef = useRef(null);
  const controlsRef = useRef(null);
  const modelRef = useRef(null);
  
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lightType, setLightType] = useState('studio'); // studio, daylight, night
  const [background, setBackground] = useState('white'); // white, gray, transparent

  // Initialize Three.js scene
  useEffect(() => {
    if (!mountRef.current) return;

    // Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xffffff);
    sceneRef.current = scene;

    // Camera
    const camera = new THREE.PerspectiveCamera(
      45,
      mountRef.current.clientWidth / mountRef.current.clientHeight,
      0.1,
      1000
    );
    camera.position.set(2, 2, 5);
    cameraRef.current = camera;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(mountRef.current.clientWidth, mountRef.current.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    mountRef.current.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.screenSpacePanning = false;
    controls.minDistance = 1;
    controls.maxDistance = 10;
    controls.maxPolarAngle = Math.PI;
    controlsRef.current = controls;

    // Lighting setup
    setupLighting(scene);

    // Add grid helper
    const gridHelper = new THREE.GridHelper(10, 10, 0x888888, 0x888888);
    gridHelper.visible = false;
    scene.add(gridHelper);

    // Load model
    if (modelUrl) {
      loadModel(modelUrl, scene);
    }

    // Animation loop
    const animate = () => {
      requestAnimationFrame(animate);
      if (controlsRef.current) {
        controlsRef.current.update();
      }
      renderer.render(scene, camera);
    };
    animate();

    // Handle resize
    const handleResize = () => {
      if (mountRef.current && camera && renderer) {
        camera.aspect = mountRef.current.clientWidth / mountRef.current.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(mountRef.current.clientWidth, mountRef.current.clientHeight);
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (renderer && mountRef.current) {
        mountRef.current.removeChild(renderer.domElement);
      }
      renderer?.dispose();
    };
  }, [modelUrl]);

  const setupLighting = (scene) => {
    // Clear existing lights
    const lightsToRemove = [];
    scene.traverse((object) => {
      if (object.isLight) lightsToRemove.push(object);
    });
    lightsToRemove.forEach(light => scene.remove(light));

    if (lightType === 'studio') {
      // Strong ambient so vertex colors are clearly visible on all sides
      const ambientLight = new THREE.AmbientLight(0xffffff, 1.2);
      scene.add(ambientLight);

      // Key light (front-left)
      const keyLight = new THREE.DirectionalLight(0xffffff, 0.8);
      keyLight.position.set(5, 5, 5);
      keyLight.castShadow = true;
      scene.add(keyLight);

      // Fill light (front-right)
      const fillLight = new THREE.DirectionalLight(0xffffff, 0.4);
      fillLight.position.set(-5, 3, 5);
      scene.add(fillLight);

      // Back light — critical for illuminating the rear of the avatar
      const backLight = new THREE.DirectionalLight(0xffffff, 0.6);
      backLight.position.set(0, 3, -6);
      scene.add(backLight);

      // Rim/top light
      const rimLight = new THREE.DirectionalLight(0xffffff, 0.3);
      rimLight.position.set(0, 8, 0);
      scene.add(rimLight);
    } else if (lightType === 'daylight') {
      // Daylight setup
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
      scene.add(ambientLight);

      const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
      directionalLight.position.set(5, 10, 7);
      directionalLight.castShadow = true;
      scene.add(directionalLight);
    } else if (lightType === 'night') {
      // Night setup
      const ambientLight = new THREE.AmbientLight(0x222222, 0.2);
      scene.add(ambientLight);

      const pointLight = new THREE.PointLight(0xffffff, 0.6, 100);
      pointLight.position.set(5, 5, 5);
      pointLight.castShadow = true;
      scene.add(pointLight);
    }
  };

  // Replace the loadModel function in your ModelViewer.jsx:

const loadModel = (url, scene) => {
  setIsLoading(true);
  setError(null);

  // For mock URLs, use test models
  let modelUrl = url;
  
  // Use test models for mock mode
  if (url.includes('mock') || url.includes('github.com')) {
    // Use a reliable test model
    modelUrl = 'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Models/master/2.0/Duck/glTF-Binary/Duck.glb';
  }

  const loader = new GLTFLoader();
  
  loader.load(
    modelUrl,
    (gltf) => {
      // Remove existing model
      if (modelRef.current) {
        scene.remove(modelRef.current);
      }

      const model = gltf.scene;
      modelRef.current = model;

      // Center the model
      const box = new THREE.Box3().setFromObject(model);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());

      model.position.x = -center.x;
      model.position.y = -center.y;
      model.position.z = -center.z;

      // Scale model to fit view
      const maxDim = Math.max(size.x, size.y, size.z);
      const scale = 3 / maxDim;
      model.scale.setScalar(scale);

      // Enable shadows
      model.traverse((node) => {
        if (node.isMesh) {
          node.castShadow = true;
          node.receiveShadow = true;
          
          // Always render both sides so the back of the avatar is visible
          // (Poisson meshes can have some inward-facing triangles on the back)
          if (node.material) {
            node.material.side = THREE.DoubleSide;
            node.material.metalness = 0.05;
            node.material.roughness = 0.85;
            // Enable vertex colors if the geometry has a COLOR_0 attribute
            if (node.geometry && node.geometry.attributes.color) {
              node.material.vertexColors = true;
            }
            node.material.needsUpdate = true;
          }
        }
      });

      scene.add(model);
      setIsLoading(false);
    },
    (progress) => {
      // Loading progress
      const percent = (progress.loaded / progress.total) * 100;
      console.log(`Loading: ${percent.toFixed(0)}%`);
    },
    (error) => {
      console.error('Error loading model:', error);
      
      // Fallback: Create a simple cube if model fails to load
      const geometry = new THREE.BoxGeometry(1, 1, 1);
      const material = new THREE.MeshStandardMaterial({ 
        color: 0x2196f3,
        metalness: 0.3,
        roughness: 0.4
      });
      const cube = new THREE.Mesh(geometry, material);
      cube.castShadow = true;
      cube.receiveShadow = true;
      
      scene.add(cube);
      modelRef.current = cube;
      
      setError('Using placeholder model - Your 3D model will load when backend is ready');
      setIsLoading(false);
    }
  );
};

  const handleResetView = () => {
    if (controlsRef.current) {
      controlsRef.current.reset();
    }
  };

  const handleZoomIn = () => {
    if (cameraRef.current) {
      cameraRef.current.position.multiplyScalar(0.9);
    }
  };

  const handleZoomOut = () => {
    if (cameraRef.current) {
      cameraRef.current.position.multiplyScalar(1.1);
    }
  };

  const handleFullscreen = () => {
    if (!document.fullscreenElement) {
      mountRef.current?.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  };

  const handleDownload = () => {
    if (modelUrl) {
      const link = document.createElement('a');
      link.href = modelUrl;
      link.download = `styleforge_3d_${Date.now()}.glb`;
      link.click();
    }
  };

  const handleLightChange = (type) => {
    setLightType(type);
    setupLighting(sceneRef.current);
  };

  const handleBackgroundChange = (bg) => {
    setBackground(bg);
    if (sceneRef.current) {
      switch (bg) {
        case 'white':
          sceneRef.current.background = new THREE.Color(0xffffff);
          break;
        case 'gray':
          sceneRef.current.background = new THREE.Color(0xf5f5f5);
          break;
        case 'transparent':
          sceneRef.current.background = null;
          break;
      }
    }
  };

  return (
    <div className="model-viewer">
      <div className="viewer-header">
        <div className="header-left">
          <Box size={24} />
          <h3>3D Model Viewer</h3>
        </div>
        <div className="header-right">
          {onClose && (
            <Button variant="ghost" size="small" onClick={onClose}>
              Close
            </Button>
          )}
        </div>
      </div>

      <div className="viewer-container">
        <div className="viewer-canvas" ref={mountRef}>
          {isLoading && (
            <div className="loading-overlay">
              <div className="spinner"></div>
              <p>Loading 3D model...</p>
            </div>
          )}
          {error && (
            <div className="error-overlay">
              <p>{error}</p>
              <Button variant="outline" size="small" onClick={() => modelUrl && loadModel(modelUrl, sceneRef.current)}>
                Retry
              </Button>
            </div>
          )}
        </div>

        <div className="viewer-controls">
          <div className="controls-group">
            <h4>View Controls</h4>
            <div className="control-buttons">
              <Button
                variant="outline"
                size="small"
                onClick={handleResetView}
                icon={RotateCw}
                title="Reset View"
              />
              <Button
                variant="outline"
                size="small"
                onClick={handleZoomIn}
                icon={ZoomIn}
                title="Zoom In"
              />
              <Button
                variant="outline"
                size="small"
                onClick={handleZoomOut}
                icon={ZoomOut}
                title="Zoom Out"
              />
              <Button
                variant="outline"
                size="small"
                onClick={handleFullscreen}
                icon={Maximize2}
                title="Fullscreen"
              />
              <Button
                variant="outline"
                size="small"
                onClick={handleDownload}
                icon={Download}
                title="Download Model"
              />
            </div>
          </div>

          <div className="controls-group">
            <h4>Lighting</h4>
            <div className="control-buttons">
              <Button
                variant={lightType === 'studio' ? 'primary' : 'outline'}
                size="small"
                onClick={() => handleLightChange('studio')}
                title="Studio Lighting"
              >
                Studio
              </Button>
              <Button
                variant={lightType === 'daylight' ? 'primary' : 'outline'}
                size="small"
                onClick={() => handleLightChange('daylight')}
                icon={Sun}
                title="Daylight"
              >
                Day
              </Button>
              <Button
                variant={lightType === 'night' ? 'primary' : 'outline'}
                size="small"
                onClick={() => handleLightChange('night')}
                icon={Moon}
                title="Night Mode"
              >
                Night
              </Button>
            </div>
          </div>

          <div className="controls-group">
            <h4>Background</h4>
            <div className="background-buttons">
              <button
                className={`bg-button ${background === 'white' ? 'active' : ''}`}
                onClick={() => handleBackgroundChange('white')}
                title="White Background"
              >
                <div className="bg-preview white"></div>
                White
              </button>
              <button
                className={`bg-button ${background === 'gray' ? 'active' : ''}`}
                onClick={() => handleBackgroundChange('gray')}
                title="Gray Background"
              >
                <div className="bg-preview gray"></div>
                Gray
              </button>
              <button
                className={`bg-button ${background === 'transparent' ? 'active' : ''}`}
                onClick={() => handleBackgroundChange('transparent')}
                title="Transparent Background"
              >
                <div className="bg-preview transparent"></div>
                Transparent
              </button>
            </div>
          </div>

          <div className="controls-group">
            <h4>Instructions</h4>
            <ul className="instructions">
              <li>Drag to rotate model</li>
              <li>Scroll to zoom in/out</li>
              <li>Right-click + drag to pan</li>
              <li>Click buttons for lighting effects</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ModelViewer;