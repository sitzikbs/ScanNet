
import os, struct
import numpy as np
import zlib
import imageio
import cv2
from plyfile import PlyData, PlyElement

COMPRESSION_TYPE_COLOR = {-1:'unknown', 0:'raw', 1:'png', 2:'jpeg'}
COMPRESSION_TYPE_DEPTH = {-1:'unknown', 0:'raw_ushort', 1:'zlib_ushort', 2:'occi_ushort'}

class RGBDFrame():

  def load(self, file_handle):
    self.camera_to_world = np.asarray(struct.unpack('f'*16, file_handle.read(16*4)), dtype=np.float32).reshape(4, 4)
    self.timestamp_color = struct.unpack('Q', file_handle.read(8))[0]
    self.timestamp_depth = struct.unpack('Q', file_handle.read(8))[0]
    self.color_size_bytes = struct.unpack('Q', file_handle.read(8))[0]
    self.depth_size_bytes = struct.unpack('Q', file_handle.read(8))[0]
    self.color_data = ''.join(struct.unpack('c'*self.color_size_bytes, file_handle.read(self.color_size_bytes)))
    self.depth_data = ''.join(struct.unpack('c'*self.depth_size_bytes, file_handle.read(self.depth_size_bytes)))


  def decompress_depth(self, compression_type):
    if compression_type == 'zlib_ushort':
       return self.decompress_depth_zlib()
    else:
       raise


  def decompress_depth_zlib(self):
    return zlib.decompress(self.depth_data)


  def decompress_color(self, compression_type):
    if compression_type == 'jpeg':
       return self.decompress_color_jpeg()
    else:
       raise


  def decompress_color_jpeg(self):
    return imageio.imread(self.color_data)


class SensorData:

  def __init__(self, filename):
    self.version = 4
    self.load(filename)


  def load(self, filename):
    with open(filename, 'rb') as f:
      version = struct.unpack('I', f.read(4))[0]
      assert self.version == version
      strlen = struct.unpack('Q', f.read(8))[0]
      self.sensor_name = ''.join(struct.unpack('c'*strlen, f.read(strlen)))
      self.intrinsic_color = np.asarray(struct.unpack('f'*16, f.read(16*4)), dtype=np.float32).reshape(4, 4)
      self.extrinsic_color = np.asarray(struct.unpack('f'*16, f.read(16*4)), dtype=np.float32).reshape(4, 4)
      self.intrinsic_depth = np.asarray(struct.unpack('f'*16, f.read(16*4)), dtype=np.float32).reshape(4, 4)
      self.extrinsic_depth = np.asarray(struct.unpack('f'*16, f.read(16*4)), dtype=np.float32).reshape(4, 4)
      self.color_compression_type = COMPRESSION_TYPE_COLOR[struct.unpack('i', f.read(4))[0]]
      self.depth_compression_type = COMPRESSION_TYPE_DEPTH[struct.unpack('i', f.read(4))[0]]
      self.color_width = struct.unpack('I', f.read(4))[0]
      self.color_height =  struct.unpack('I', f.read(4))[0]
      self.depth_width = struct.unpack('I', f.read(4))[0]
      self.depth_height =  struct.unpack('I', f.read(4))[0]
      self.depth_shift =  struct.unpack('f', f.read(4))[0]
      num_frames =  struct.unpack('Q', f.read(8))[0]
      self.frames = []
      for i in range(num_frames):
        frame = RGBDFrame()
        frame.load(f)
        self.frames.append(frame)


  def export_depth_images(self, output_path, image_size=None, frame_skip=1):
    if not os.path.exists(output_path):
      os.makedirs(output_path)
    print 'exporting', len(self.frames)//frame_skip, ' depth frames to', output_path
    for f in range(0, len(self.frames), frame_skip):
      depth_data = self.frames[f].decompress_depth(self.depth_compression_type)
      depth = np.fromstring(depth_data, dtype=np.uint16).reshape(self.depth_height, self.depth_width)
      if image_size is not None:
        depth = cv2.resize(depth, (image_size[1], image_size[0]), interpolation=cv2.INTER_NEAREST)
      imageio.imwrite(os.path.join(output_path, str(f) + '.png'), depth)


  def export_color_images(self, output_path, image_size=None, frame_skip=1):
    if not os.path.exists(output_path):
      os.makedirs(output_path)
    print 'exporting', len(self.frames)//frame_skip, 'color frames to', output_path
    for f in range(0, len(self.frames), frame_skip):
      color = self.frames[f].decompress_color(self.color_compression_type)
      if image_size is not None:
        color = cv2.resize(color, (image_size[1], image_size[0]), interpolation=cv2.INTER_NEAREST)
      imageio.imwrite(os.path.join(output_path, str(f) + '.jpg'), color)


  def save_mat_to_file(self, matrix, filename):
    with open(filename, 'w') as f:
      for line in matrix:
        np.savetxt(f, line[np.newaxis], fmt='%f')


  def export_poses(self, output_path, frame_skip=1):
    if not os.path.exists(output_path):
      os.makedirs(output_path)
    print 'exporting', len(self.frames)//frame_skip, 'camera poses to', output_path
    for f in range(0, len(self.frames), frame_skip):
      self.save_mat_to_file(self.frames[f].camera_to_world, os.path.join(output_path, str(f) + '.txt'))


  def export_intrinsics(self, output_path):
    if not os.path.exists(output_path):
      os.makedirs(output_path)
    print 'exporting camera intrinsics to', output_path
    self.save_mat_to_file(self.intrinsic_color, os.path.join(output_path, 'intrinsic_color.txt'))
    self.save_mat_to_file(self.extrinsic_color, os.path.join(output_path, 'extrinsic_color.txt'))
    self.save_mat_to_file(self.intrinsic_depth, os.path.join(output_path, 'intrinsic_depth.txt'))
    self.save_mat_to_file(self.extrinsic_depth, os.path.join(output_path, 'extrinsic_depth.txt'))

  def export_point_clouds(self, output_path, frame_skip=1, pc_normalize=True, output_type='ply'):
    if not os.path.exists(output_path):
      os.makedirs(output_path)
    print 'exporting', len(self.frames) // frame_skip, 'point clouds to', output_path

    intrinsicInv = np.linalg.inv(self.intrinsic_depth)

    for f in range(0, len(self.frames), frame_skip):
      color = self.frames[f].decompress_color(self.color_compression_type)
      depth_data = self.frames[f].decompress_depth(self.depth_compression_type)
      depth = np.fromstring(depth_data, dtype=np.uint16).reshape(self.depth_height, self.depth_width)
      transform = self.frames[f].camera_to_world
      if transform[0][0] == -float("inf") or transform[0][0] == 0:
          transform = np.identity(4)

      pc_xyz = []
      pc_color = []
      for y in range(self.depth_height):
        for x in range(self.depth_width):

          if depth[y][x] != 0:
            # extract coordinates
            d = float(depth[y][x]) / self.depth_shift
            camera_pos = np.dot(intrinsicInv, np.array([float(x) * d, float(y) * d, d, 0.0]))
            world_pos =  np.dot(transform, camera_pos)
            pc_xyz.append(np.array(world_pos[0:3]))

            # extract color
            color_frame_pos = np.dot(self.extrinsic_depth, camera_pos)
            color_coord = np.dot(self.intrinsic_color, color_frame_pos)
            color_coord[0] = color_coord[0] / color_coord[2]
            color_coord[1] = color_coord[1] / color_coord[2]
            color_coord = np.round(color_coord).astype(int)
            if 0 <= color_coord[0] < self.color_width and 0 <= color_coord[1] < self.color_height:
              point_color = np.concatenate([color[color_coord[1]][color_coord[0]], [255.0]]) / 255.0
            else:
              point_color = np.array([0.0, 0.0, 0.0, 0.0])
            pc_color.append(point_color)
      if pc_normalize:
        # center around COG an scale to unit sphere
        center = np.mean(pc_xyz, axis=0)
        pc_xyz = pc_xyz - center
        scale = np.max(np.sqrt(np.sum(pc_xyz ** 2, axis=1)))
        pc_xyz = pc_xyz / scale

      pc = np.array(np.concatenate([pc_xyz, pc_color], axis=1)).astype(np.float16) # add center and normalize?
      if output_type == 'txt':
        self.save_mat_to_file(pc, os.path.join(output_path, str(f) + '.txt'))
      elif output_type == 'npy':
        file_name = os.path.join(output_path, str(f) + '.npy')
        np.save(file_name, pc)
      else:
        file_name = os.path.join(output_path, str(f) + '.ply')
        new_vertices = []
        for vertex in pc:
          new_vertices.append(
            (vertex[0], vertex[1], vertex[2], (255 * vertex[3]).astype(int), (255 * vertex[4]).astype(int),
             (255 * vertex[5]).astype(int), vertex[6]))

        new_vertices = np.array(new_vertices, dtype=[('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
                                                     ('red', 'u1'), ('green', 'u1'), ('blue', 'u1'), ('alpha', 'f4')])
        el = PlyElement.describe(new_vertices, 'vertex')
        PlyData([el]).write(file_name)


