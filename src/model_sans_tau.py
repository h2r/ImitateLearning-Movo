import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

class SpatialSoftmax(nn.Module):
    """
    Spatial Softmax Implementation
    """
    def __init__(self, height, width, channel):
        super(SpatialSoftmax, self).__init__()
        self.height = height
        self.width = width
        self.channel = channel

        pos_x, pos_y = np.meshgrid(
            np.linspace(-1., 1., self.height),
            np.linspace(-1., 1., self.width))
        pos_x = torch.from_numpy(pos_x.reshape(self.height*self.width)).float()
        pos_y = torch.from_numpy(pos_y.reshape(self.height*self.width)).float()
        self.register_buffer('pos_x', pos_x)
        self.register_buffer('pos_y', pos_y)

    def forward(self, feature):
        feature = feature.view(-1, self.height*self.width)
        softmax_attention = F.softmax(feature, dim=-1)
        expected_x = torch.sum(self.pos_x*softmax_attention, dim=1, keepdim=True)
        expected_y = torch.sum(self.pos_y*softmax_attention, dim=1, keepdim=True)
        expected_xy = torch.cat([expected_x, expected_y], 1)
        feature_keypoints = expected_xy.view(-1, self.channel*2)

        return feature_keypoints


class Model(nn.Module):
    """
    The net implemented from Deep Imitation Learning from Virtual Teleoperation with parameterization
    """
    def __init__(self, use_bias=True, eof_size=15, tau_size=3, aux_size=6, out_size=7):
        super(Model, self).__init__()
        self.use_bias = use_bias
        self.eof_size = eof_size
        self.tau_size = tau_size
        self.aux_size = aux_size
        self.out_size = out_size

        # Note that all of the layers have valid padding
        self.layer1_rgb = nn.Conv2d(3, 64, kernel_size=7, stride=2, bias=use_bias)
        self.layer1_depth = nn.Conv2d(1, 16, kernel_size=7, stride=2, bias=use_bias)

        self.conv1 = nn.Conv2d(80, 32, kernel_size=1, bias=use_bias)
        self.conv2 = nn.Conv2d(32, 32, kernel_size=3, bias=use_bias)
        self.conv3 = nn.Conv2d(32, 32, kernel_size=3, bias=use_bias)
        self.spatial_softmax = SpatialSoftmax(53, 73, 32)

        # Testing the auxiliary for finding final pose. It was shown in many tasks that
        # predicting the final pose was a helpful auxiliary task. EE Pose is <x,y,z,q_x,q_y,q_z,q_w>.
        # Note that the output from the spatial softmax is 32 (x,y) positions and thus 64 variables
        self.aux = nn.Sequential(nn.Linear(64 + tau_size, 40, bias=use_bias),
                                 nn.ReLU(),
                                 nn.Linear(40, aux_size, bias=use_bias))
        # This is where the concatenation of the output from spatialsoftmax
        self.fl1 = nn.Linear(64 + tau_size, 50, bias=use_bias)
        # Concatenating the Auxiliary Predictions and EE history. Past 5 history of <x,y,z>.
        # This comes out to 50 + 6 (aux) + 15 (ee history) = 71\
        self.fl2 = nn.Linear(50+eof_size+aux_size, 50, bias=use_bias)

	    # We use 6 to incorporate the loss function (linear vel, angular vel)
        self.output = nn.Linear(50, out_size, bias=use_bias)

        # Initialize the weights
        nn.init.uniform_(self.layer1_rgb.weight,a=-0.01,b=0.01)
        nn.init.uniform_(self.layer1_depth.weight,a=-0.01,b=0.01)
        # Convolutional Weight Updates
        nn.init.uniform_(self.conv1.weight,a=-0.01,b=0.01)
        nn.init.uniform_(self.conv2.weight,a=-0.01,b=0.01)
        nn.init.uniform_(self.conv3.weight,a=-0.01,b=0.01)
        for i in range(0,3,2):
            nn.init.uniform_(self.aux[i].weight,a=-0.01,b=0.01)
        nn.init.uniform_(self.fl1.weight,a=-0.01,b=0.01)
        nn.init.uniform_(self.fl2.weight,a=-0.01,b=0.01)
        nn.init.uniform_(self.output.weight,a=-0.01,b=0.01)

    def forward(self, rgb, depth, eof, tau):
        x_rgb = self.layer1_rgb(rgb)
        x_depth = self.layer1_depth(depth)
        x = F.relu(torch.cat([x_rgb, x_depth], dim=1))

        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = F.relu(self.conv3(x))
        x = self.spatial_softmax(x)
        x = torch.cat([x, tau], dim=1)

        aux = self.aux(x)

        x = F.relu(self.fl1(x))
        x = self.fl2(torch.cat([aux, x, eof], dim=1))
        x = self.output(x)


        return x, aux